#!/usr/bin/env python3
"""Validate and publish exactly one next lecture PDF.

The command is intentionally dependency-free. It uses ``pdfinfo`` when
available for page-count validation and falls back to checking the PDF header.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "course.json"
STATE_PATH = ROOT / "release-state.json"
MANIFEST_PATH = ROOT / "published" / "manifest.json"
INDEX_PATH = ROOT / "published" / "README.md"


class ReleaseError(RuntimeError):
    """A user-actionable release validation error."""


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"无法读取 {path.relative_to(ROOT)}: {exc}") from exc


def atomic_write_json(path: Path, value: dict) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_page_count(path: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return None
    result = subprocess.run(
        [pdfinfo, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReleaseError(f"PDF 校验失败：{path.name}: {result.stderr.strip()}")
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError as exc:
                raise ReleaseError(f"无法解析 {path.name} 的页数") from exc
    raise ReleaseError(f"pdfinfo 未返回 {path.name} 的页数")


def validate_pdf(path: Path) -> tuple[int | None, str, int]:
    if not path.is_file():
        raise ReleaseError(f"源文件不存在：{path.relative_to(ROOT)}")
    size = path.stat().st_size
    if size < 1024:
        raise ReleaseError(f"PDF 文件过小，疑似损坏：{path.name}")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ReleaseError(f"文件不是有效 PDF：{path.name}")
    pages = pdf_page_count(path)
    if pages is not None and pages < 1:
        raise ReleaseError(f"PDF 没有页面：{path.name}")
    return pages, sha256(path), size


def validate_state(config: dict, state: dict, manifest: dict) -> list[int]:
    total = config.get("total_lectures")
    if not isinstance(total, int) or total < 1:
        raise ReleaseError("course.json 中 total_lectures 必须是正整数")
    if total != 16:
        raise ReleaseError("当前发布计划必须严格包含 16 讲")

    released = state.get("released")
    if not isinstance(released, list) or not all(isinstance(n, int) for n in released):
        raise ReleaseError("release-state.json 中 released 必须是整数列表")
    if released != list(range(1, len(released) + 1)):
        raise ReleaseError("已发布讲次必须从第 1 讲开始连续，不能跳号或重复")

    entries = manifest.get("lectures")
    if not isinstance(entries, list):
        raise ReleaseError("manifest.json 中 lectures 必须是列表")
    manifest_numbers = [entry.get("number") for entry in entries]
    if manifest_numbers != released:
        raise ReleaseError("发布状态与 manifest.json 不一致")

    destination = ROOT / config["destination_directory"]
    actual_numbers = []
    for path in sorted(destination.glob("lecture[0-9][0-9].pdf")):
        actual_numbers.append(int(path.stem.removeprefix("lecture")))
    if actual_numbers != released:
        raise ReleaseError("published/lectures 中的 PDF 与发布状态不一致")
    return released


def source_path(config: dict, number: int) -> Path:
    relative = config["source_pattern"].format(number=number)
    return ROOT / relative


def release_window(config: dict, now: datetime) -> tuple[datetime, int]:
    try:
        start_date = date.fromisoformat(config["release_start_date"])
        hour, minute = (int(part) for part in config["release_time"].split(":"))
        timezone = ZoneInfo(config["timezone"])
        start = datetime.combine(start_date, time(hour, minute), tzinfo=timezone)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseError("course.json 中的发布日期、时间或时区无效") from exc
    local_now = now.astimezone(timezone)
    if local_now < start:
        return start, 0
    weeks = (local_now - start) // timedelta(days=7)
    available = min(config["total_lectures"], int(weeks) + 1)
    return start, available


def render_index(config: dict, manifest: dict) -> str:
    entries = manifest["lectures"]
    lines = [
        "# 已发布讲义",
        "",
        (
            f"本课程共 {config['total_lectures']} 讲，按计划于北京时间每周四 "
            f"{config['release_time']} 发布一讲。"
        ),
        "",
    ]
    if not entries:
        lines.extend(
            [
                "尚未发布讲义。首讲计划由自动化任务在下一个周四 12:00（北京时间）发布。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "| 讲次 | 文件 | 页数 | 发布时间 |",
                "| ---: | --- | ---: | --- |",
            ]
        )
        for entry in entries:
            page_text = str(entry["pages"]) if entry["pages"] is not None else "未检测"
            lines.append(
                f"| {entry['number']:02d} | "
                f"[{entry['filename']}](lectures/{entry['filename']}) | "
                f"{page_text} | {entry['released_at']} |"
            )
        lines.append("")
    lines.extend(
        [
            "> 本文件由 `tools/release_next.py` 自动维护，请勿手工修改。",
            "",
        ]
    )
    return "\n".join(lines)


def copy_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    try:
        shutil.copy2(source, temp_name)
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def command_check(config: dict, state: dict, manifest: dict) -> int:
    released = validate_state(config, state, manifest)
    next_number = len(released) + 1
    if next_number > config["total_lectures"]:
        print("发布计划已完成：16/16。")
        return 0
    path = source_path(config, next_number)
    pages, digest, size = validate_pdf(path)
    now = datetime.now(ZoneInfo(config["timezone"]))
    start, available = release_window(config, now)
    page_text = str(pages) if pages is not None else "未检测（pdfinfo 不可用）"
    print(f"下一讲：{next_number:02d}")
    print(f"源文件：{path.relative_to(ROOT)}")
    print(f"页数：{page_text}")
    print(f"大小：{size} bytes")
    print(f"SHA-256：{digest}")
    if next_number <= available:
        print("发布窗口：已开放")
    else:
        next_time = start + timedelta(weeks=next_number - 1)
        print(f"发布窗口：{next_time.isoformat()} 开放")
    print("预检通过；未修改任何文件。")
    return 0


def command_audit(config: dict, state: dict, manifest: dict) -> int:
    released = validate_state(config, state, manifest)
    total_bytes = 0
    print("讲次  页数  文件大小  SHA-256（前 12 位）")
    for number in range(1, config["total_lectures"] + 1):
        path = source_path(config, number)
        pages, digest, size = validate_pdf(path)
        total_bytes += size
        page_text = str(pages) if pages is not None else "?"
        print(f"{number:02d}    {page_text:>3}  {size:>8}  {digest[:12]}")
    print(
        f"全量校验通过：源文件 16/16，已发布 {len(released)}/16，"
        f"总大小 {total_bytes} bytes。"
    )
    return 0


def command_apply(config: dict, state: dict, manifest: dict) -> int:
    released = validate_state(config, state, manifest)
    next_number = len(released) + 1
    if next_number > config["total_lectures"]:
        print("发布计划已完成：16/16；没有文件需要更新。")
        return 0

    now = datetime.now(ZoneInfo(config["timezone"])).replace(microsecond=0)
    start, available = release_window(config, now)
    if next_number > available:
        next_time = start + timedelta(weeks=next_number - 1)
        print(f"尚未到第 {next_number:02d} 讲的发布窗口：{next_time.isoformat()}")
        print("未修改任何文件。")
        return 0

    source = source_path(config, next_number)
    pages, digest, size = validate_pdf(source)
    filename = f"lecture{next_number:02d}.pdf"
    destination = ROOT / config["destination_directory"] / filename
    if destination.exists():
        raise ReleaseError(f"目标文件已存在，拒绝覆盖：{destination.relative_to(ROOT)}")

    entry = {
        "number": next_number,
        "filename": filename,
        "pages": pages,
        "bytes": size,
        "sha256": digest,
        "released_at": now.isoformat(),
    }
    new_manifest = dict(manifest)
    new_manifest["lectures"] = [*manifest["lectures"], entry]
    new_state = {"released": [*released, next_number]}

    copy_atomically(source, destination)
    try:
        atomic_write_json(MANIFEST_PATH, new_manifest)
        atomic_write_json(STATE_PATH, new_state)
        atomic_write_text(INDEX_PATH, render_index(config, new_manifest))
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    validate_state(config, new_state, new_manifest)
    print(f"已发布第 {next_number:02d} 讲：{destination.relative_to(ROOT)}")
    print("需要提交的文件：")
    print(f"  {destination.relative_to(ROOT)}")
    print(f"  {MANIFEST_PATH.relative_to(ROOT)}")
    print(f"  {STATE_PATH.relative_to(ROOT)}")
    print(f"  {INDEX_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="校验或发布下一份高数讲义")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="预检下一讲，不修改文件")
    action.add_argument("--audit", action="store_true", help="校验全部 16 讲，不修改文件")
    action.add_argument("--apply", action="store_true", help="发布下一讲并更新清单")
    args = parser.parse_args()

    try:
        config = load_json(CONFIG_PATH)
        state = load_json(STATE_PATH)
        manifest = load_json(MANIFEST_PATH)
        if args.check:
            return command_check(config, state, manifest)
        if args.audit:
            return command_audit(config, state, manifest)
        return command_apply(config, state, manifest)
    except ReleaseError as exc:
        print(f"发布失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
