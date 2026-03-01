# ToolA → ToolB → ToolC 工作流銜接驗證報告

驗證方法：逐一追蹤每個資料契約介面（data contract），確認輸出端格式與輸入端期望完全對應。

---

## 介面一：ToolA → ToolB（features_raw.jsonl）

### 欄位對應矩陣

| ToolB 讀取欄位 | ToolA 輸出欄位 | 狀態 |
|---|---|---|
| `global_stats.framework.detected` | ✅ 存在 | OK |
| `global_stats.framework.confidence` | ✅ 存在 | OK |
| `global_stats.framework.evidence` | ✅ 存在 | OK |
| `global_stats.scan_summary.*` | ✅ 存在（5個子欄位） | OK |
| `global_stats.signal_frequency_table[].signal` | ✅ 存在 | OK |
| `global_stats.signal_frequency_table[].false_positive_risk_reason` | ✅ 存在 | OK |
| `global_stats.custom_helper_registry[].seen_in_files` | ❌ **ToolA 使用 `seen_called_in_files`** | **BUG #1** |
| `global_stats.pattern_json_generation_hints.recommended_uncertain_threshold` | ✅ 存在 | OK |
| `global_stats.pattern_json_generation_hints.uncertain_threshold_basis` | ✅ 存在（本次新增）| OK |
| `global_stats.pattern_json_generation_hints.minimum_threshold_gap` | ✅ 存在（本次新增）| OK |
| `global_stats.pattern_json_generation_hints.score_distribution_summary` | ✅ 存在（本次新增）| **未出現在 ToolB 的 JSONL_EVIDENCE_BLOCK** → BUG #2 |
| `file.signals.strong[].occurrences` | ✅ 存在 | OK |
| `file.signals.strong[].global_seen_in_files` | ✅ 存在 | OK |
| `file.route_hints[].source` | ❌ **ToolA JSONL 實際輸出 `source_file` + `source_line` 分開欄位** | **BUG #3** |
| `file.custom_helpers_called[].name` | ✅ 存在 | OK |
| `file.method_hints[].method` | ✅ 存在 | OK |
| `file.input_params.get[].key` | ✅ 存在 | OK |
| `file.envelope_keys[].key` | ✅ 存在 | OK |

### 問題詳述

**BUG #1 — 欄位名稱不一致（ToolA custom_helper_registry）**

ToolA JSONL 輸出：
```json
{ "helper_name": "apiResponse", "seen_called_in_files": 15, ... }
```

ToolB JSONL_EVIDENCE_BLOCK 表格標題：
```
| Helper Name | Wraps Signal | Seen In Files | ...
```
實作者若照 column header 去取 `seen_in_files` 欄位會 KeyError。
必須改為明確讀取 `seen_called_in_files`。

**BUG #2 — ToolB JSONL_EVIDENCE_BLOCK 遺漏三個新欄位**

ToolA 現在輸出但 ToolB 的 prompt evidence 完全未引用：
- `score_distribution_summary`（p25/p50/p75/p90）— AI agent 無法靠分布資料校準 threshold
- `minimum_threshold_gap` + `minimum_threshold_gap_note` — AI agent 不知道間距約束
- `uncertain_threshold_basis`（有文字說明）— AI agent 拿不到推算依據說明

同時，ToolB 第 318 行還保留舊邏輯：
```
Recommended uncertain threshold: {value}  [derived as endpoint * 0.5]
```
應改為直接讀 `recommended_uncertain_threshold`（已由 ToolA 實測計算），
並展示 `uncertain_threshold_basis` 讓 AI agent 理解數值的依據。

**BUG #3 — route_hints 格式不一致（ToolA 內部 + 跨工具）**

ToolA Route Mapping 說明章節（舊格式）：
```json
{ "method": "POST", "uri": "/api/users", "source": "routes/api.php:14" }
```

ToolA JSONL 實際 file record schema（新格式）：
```json
{ "method": "POST", "uri": "/api/users", "source_file": "routes/api.php", "source_line": 14, "confidence": "high" }
```

**ToolA 內部有兩種格式，相互矛盾。** 實作者會不知道該用哪個。
ToolB evidence block 的 `{route_hints formatted as METHOD URI (source)}` 也未說明如何合併 `source_file` + `source_line`。

---

## 介面二：ToolB → ToolC（pattern.json）

### 欄位對應矩陣

| ToolC 讀取欄位 | ToolB 輸出保證 | 狀態 |
|---|---|---|
| `version` | ✅ AI agent 輸出，ToolB 驗證 | OK |
| `source_jsonl_schema_version` | ✅ AI agent 應輸出 "2.0" | **V1-V12 無規則驗證此欄位** → BUG #4 |
| `framework` | ✅ AI agent 輸出，V7 驗證 | OK |
| `scoring.strong_signals[].weight` 範圍 [1,50] | ✅ V4 驗證正整數，ToolB schema block 說明範圍 | OK |
| `scoring.negative_signals[].weight` 為負 | ✅ V3 驗證 | OK |
| `thresholds.uncertain < thresholds.endpoint` | ✅ V2 驗證 | OK |
| `thresholds gap ≥ minimum_threshold_gap` | ✅ V12 驗證（新增）| OK |
| `endpoint_envelopes.templates[].name` 唯一 | ✅ V8 驗證 | OK |
| `method_inference.priority_order` 末尾為 "default" | ✅ V9 驗證 | OK |
| `_tool_b_meta`（extension field）| ✅ V11 靜默忽略 | OK |
| ToolB 本身的 `validator.py` 規則版本 | ❌ **ToolB 說 V1-V10，ToolC 說 V1-V12** | **BUG #5** |

### 問題詳述

**BUG #4 — `source_jsonl_schema_version` 欄位無驗證規則**

ToolC schema 定義此欄位為 required 且必須為 "2.0"，但 V1-V12 驗證規則表中**沒有任何一條**驗證它。
ToolC 會驗證 JSONL 的 `schema_version`（啟動序列步驟 1），但不會驗證 `pattern.json` 內的 `source_jsonl_schema_version`。
若 AI agent 填錯版本號，不會被攔截。

**BUG #5 — ToolB 驗證規則版本落後**

ToolB prompt 三處引用舊版規則數量：
- Module Architecture：`validator.py — Runs V1–V10 validation rules`
- Quality Bar：`ToolB's validation rules must be identical to ToolC's V1–V10`
- 均未提及 `toolchain_validator.py` 共用模組

ToolC 現在已有 V1-V12 + 共用 `toolchain_validator.py`。
ToolB 的規則庫若未同步更新，兩者實際執行的驗證行為會分歧。
特別是 V11（extension field 忽略）和 V12（gap 約束），ToolB 若未實作，
可能在驗證 AI agent 輸出時拒絕帶有 `_tool_b_meta` 的 JSON，形成自我矛盾。

---

## 介面三：ToolC → Postman（輸出端驗證）

### 欄位追蹤

| ToolC 引用的 JSONL 欄位 | ToolA 實際輸出 | 狀態 |
|---|---|---|
| `file.signals.strong[].occurrences`（re-scoring 乘數）| ✅ 存在 | OK |
| `file.route_hints[].confidence`（method inference priority）| ✅ 存在於 JSONL schema | **但 ToolA Route Mapping 說明章節沒有此欄位** → 同 BUG #3 |
| `file.input_params.json_body[].key`（body skeleton 生成）| ✅ 存在 | OK |
| `file.envelope_keys[].key`（template matching）| ✅ 存在 | OK |
| `file.score`（ToolA cross-check）| ✅ 存在 | OK |
| `global_stats.pattern_json_generation_hints.minimum_threshold_gap`（V12）| ✅ 存在 | OK |

---

## 問題匯總與嚴重程度

| # | 位置 | 問題 | 嚴重度 | 影響 |
|---|---|---|---|---|
| BUG #1 | ToolB JSONL_EVIDENCE_BLOCK | `seen_in_files` vs `seen_called_in_files` 欄位名稱 | 🔴 High | 實作者 KeyError；AI agent 看不到 helper 呼叫頻率 |
| BUG #2 | ToolB JSONL_EVIDENCE_BLOCK | 遺漏 `score_distribution_summary`、`minimum_threshold_gap`、`uncertain_threshold_basis`；保留 `endpoint * 0.5` 舊推算邏輯 | 🔴 High | AI agent 無法正確校準 threshold；違背 ToolA 新增欄位的設計意圖 |
| BUG #3 | ToolA Route Mapping 章節 + ToolB evidence block | `source` vs `source_file`+`source_line`+`confidence` 格式不一致 | 🔴 High | ToolA 內部矛盾；ToolB/ToolC 實作者無所適從 |
| BUG #4 | ToolC 驗證規則表 | `source_jsonl_schema_version` 欄位無驗證規則（V1-V12 均未覆蓋）| 🟡 Medium | 版本錯填不被攔截；跨版本 pattern.json 可能靜默通過 |
| BUG #5 | ToolB module + Quality Bar | 引用 V1-V10 + 未採用 `toolchain_validator.py` | 🟡 Medium | ToolB 驗證邏輯與 ToolC 分歧；V11/V12 未在 ToolB 實作 |

---

## 修復清單（最小改動）

### ToolA（1 處）
- [ ] 將 Route Mapping 說明章節的 `route_hints` 範例格式統一為：
  `{ "method", "uri", "source_file", "source_line", "confidence" }`
  刪除舊的 `source` 合併字串格式

### ToolB（2 處）
- [ ] JSONL_EVIDENCE_BLOCK：
  - 將 Custom Helper 表格的 `Seen In Files` 欄位明確標注讀取 `seen_called_in_files`
  - 替換 `[derived as endpoint * 0.5]` 為直接讀取 `recommended_uncertain_threshold`
  - 新增 `uncertain_threshold_basis`、`score_distribution_summary`、`minimum_threshold_gap` 三個段落至 Evidence Block
  - 修正 route_hints 格式描述為 `METHOD URI (source_file:source_line)` [confidence]
- [ ] Module Architecture + Quality Bar：
  - 將 `validator.py` 改為引用 `toolchain_validator` 共用模組
  - 將 V1-V10 改為 V1-V12
  - 補充 V11（extension field）和 V12（gap 約束）對 ToolB 自身的影響說明

### ToolC（1 處）
- [ ] 驗證規則表新增 V13：
  `pattern.json` 的 `source_jsonl_schema_version` 必須為 `"2.0"`，
  不符合 → Warning（不 Exit 1，因為 ToolC 已在啟動序列驗證 JSONL 版本，
  此處為 pattern.json 自申告的版本一致性檢查）
