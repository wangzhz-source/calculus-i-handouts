# 高等数学 I 每周讲义

本仓库按周发布 16 份《高等数学 I》讲义。计划在北京时间每周四 12:00 发布一讲；已发布文件位于 [`published/lectures/`](published/lectures/)，发布记录见 [`published/manifest.json`](published/manifest.json)。

## 发布规则

- 总讲数：16 讲。
- 首次发布：2026-09-17（周四）12:00。
- 最后发布：2026-12-31（周四）12:00。
- 发布频率：每周 1 讲。
- 发布时间：每周四 12:00（Asia/Shanghai）。
- 文件命名：`lecture01.pdf` 至 `lecture16.pdf`。
- 发布顺序：只能连续发布，不能跳号。
- 自动化：每次运行先校验 PDF，再复制下一讲并更新清单；同一周重复运行不会提前释放下一讲。

## 仓库结构

```text
.
├── course.json               # 课程与发布时间配置
├── release-state.json        # 发布状态（机器维护）
├── published/
│   ├── README.md             # 面向读者的已发布目录
│   ├── manifest.json         # 带哈希值的发布清单
│   └── lectures/             # 对外发布的 PDF
└── tools/
    └── release_next.py       # 校验并发布下一讲
```

原始 LaTeX、构建产物、教材和未发布 PDF 都保留在本机工作区，但通过 `.gitignore` 排除，不会意外进入公开仓库或 Git 历史。

## 本地使用

预检下一次发布：

```bash
python3 tools/release_next.py --check
```

校验全部 16 讲：

```bash
python3 tools/release_next.py --audit
```

发布下一讲：

```bash
python3 tools/release_next.py --apply
```

发布后只需提交脚本列出的文件；自动化任务会在每周四中午执行同一流程。

## 首次连接远程仓库

```bash
git remote add origin <你的仓库地址>
git push -u origin main
```

远程地址未配置前，自动化只能完成本地发布和校验，不能推送到 GitHub、GitLab 或其他托管平台。
