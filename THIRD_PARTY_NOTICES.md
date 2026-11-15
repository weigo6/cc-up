# 第三方组件与许可证声明

本项目自身以 MIT 许可证发布，见 [`LICENSE`](LICENSE)。

## CC-Switch

`cc_up/rules.py` 与 `cc_up/database.py` 中的部分 SQL 聚合规则移植自
[farion1231/cc-switch](https://github.com/farion1231/cc-switch)，commit
`27e2cffa91c091469d8106e679cae2772d47c8dd`：

- `src-tauri/src/services/sql_helpers.rs`
- `src-tauri/src/services/usage_stats.rs`

这些部分适用以下许可证：

```text
MIT License

Copyright (c) 2025 Jason Young

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 前端

`frontend/` 下的页面是手写的 HTML / CSS / JavaScript，不使用外部 CDN、字体、
分析脚本或图表库，不包含第三方前端代码。
