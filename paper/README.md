# 论文包生成

`generator.py` 从**已落盘的证据**（规则、数据审计、实验记录）生成一份可溯源的论文包：
`competition_report.tex` + `references.bib` + `evidence_map.json`（每条结论指向具体的实验或报告）。
它不虚构任何未记录的结果。

```powershell
python main.py paper                      # 生成到当前工作区的 paper/generated/
python main.py paper --workspace workspace/<项目 id>
```

**产物落在工作区里**（`<workspace>/paper/generated/`），不落在本目录 —— 证据属于项目，
必须跟着工作区走，换台机器拷贝工作区就能重新读出来（见 `docs/architecture.md` D2）。

本目录只有生成器本身。论文正文、表格、图都从证据生成，不在这里手写。
