# 提交文件说明（Submission Format Specification）

参赛者需提交预测结果文件（以下简称 **output 文件**）。假设评测集包含
**5000
条数据**，提交文件必须满足以下格式与规则，否则系统将返回对应错误信息。

------------------------------------------------------------------------

# 1. 文件要求

提交文件需满足以下要求：

-   **文件名：** `output.json`
-   **文件格式：** JSON
-   **文件编码：** UTF-8

提交文件应为一个 **JSON 数组（JSON Array）**，数组中包含 **5000
条预测结果**，每条结果为一个 JSON 对象。

示例结构：

``` json
[
  {"id": 1, "factivity": "true", "confidence": 0.87},
  {"id": 2, "factivity": "false", "confidence": 0.73},
  {"id": 3, "factivity": "uncertain", "confidence": null}
]
```

------------------------------------------------------------------------

# 2. 文件校验规则

## 2.1 文件格式校验

若提交文件不是合法 JSON 文件，系统将返回错误：

    file format error: JSON is expected.

## 2.2 文件编码校验

若提交文件编码不是 UTF-8，系统将返回错误：

    file encoding error: UTF-8 is expected.

------------------------------------------------------------------------

# 3. 数据条数要求

提交文件中的数据条数必须 **严格等于 5000 条**。

若数据条数多于或少于 5000 条，系统将返回错误：

    object quantity error: 5000 objects are expected.

------------------------------------------------------------------------

# 4. 数据字段要求

提交文件中的每条数据 **必须且只能包含以下三个字段**：

  |字段名       |数据类型           |说明
  |------------ |-------------- |------------
  |id           |integer        |数据编号
  |factivity    |string         |事实性判断
  |confidence   |float / null   |模型置信度

## 4.1 字段数量检查

若某条数据字段数量不为 3，系统将返回错误：

    field quantity error in line XXX: 3 fields are expected

其中 `XXX` 为 output 文件中的行号。

## 4.2 字段名称检查

若字段名称不符合要求（必须为
`id`、`factivity`、`confidence`），系统将返回错误：

    field name error in line XXX: "id", "factivity", "confidence" are expected.

------------------------------------------------------------------------

# 5. 字段取值规则

## 5.1 id 字段

`id` 字段必须满足以下要求：

-   取值范围为 **1--5000**
-   每个 `id` **只能出现一次**
-   必须与评测集 **一一对应**
-   **必须按 id 升序排列**

示例：

    1, 2, 3, 4, ..., 5000

若不满足上述条件，系统将返回错误：

    field value error in line XXX: "id" must be an integer in [1, 5000] and sorted in ascending order.

## 5.2 factivity 字段

`factivity` 字段的合法取值为：

    true
    false
    uncertain

若出现其他取值，系统将返回错误：

    field value error in line XXX: "factivity" must be one of {"true", "false", "uncertain"}.

## 5.3 confidence 字段

### 情况一："factivity" = "true" 或 "false"

当 `factivity` 为 `true` 或 `false` 时，`confidence` 字段必须满足：

-   不允许为空
-   必须为数值类型
-   取值范围 **(0.50, 1.00\]**
-   **不包含 0.50**
-   **包含 1.00**
-   **保留两位小数**

合法示例：

    0.51
    0.76
    0.95
    1.00

若不满足要求，系统将返回错误：

    field value error in line XXX: "confidence" must be a number in (0.50, 1.00] with two decimal places.

### 情况二："factivity" = "uncertain"

当 `factivity` 为 `uncertain` 时：

`confidence` 字段**必须为空**（`null`）。

若不满足要求，系统将返回错误：

    field value error in line XXX: "confidence" must be null when "factivity" is "uncertain".

------------------------------------------------------------------------

# 6. 提交文件示例

示例（output.json）：

``` json
[
  {"id": 1, "factivity": "true", "confidence": 0.87},
  {"id": 2, "factivity": "false", "confidence": 0.73},
  {"id": 3, "factivity": "uncertain", "confidence": null},
  {"id": 4, "factivity": "true", "confidence": 0.91}
]
```

------------------------------------------------------------------------

# 7. 常见错误示例

 | 错误类型                         |示例|
  |-------------------------------- |----------------------|
  |数据条数错误                     |4999 条或 5001 条|
  |字段数量错误                     |少于或多于 3 个字段|
  |字段名称错误                     |`fact`, `score`|
  |id 未升序                       | `1,3,2`|
  |id 重复                         | 两条记录 `id=15`|
  |confidence 超范围               | `0.40`|
  |confidence 小数位错误            |`0.756`|
  |uncertain 但 confidence 不为空   |`"confidence": 0.60`|

------------------------------------------------------------------------

# 8. 错误信息说明

所有错误信息遵循统一格式：

    <error type> [in line XXX]: <expected condition>

示例：

  |Error Message            |含义
  |------------------------ |--------------------
  |`file format error`      |文件不是合法 JSON
  |`file encoding error`    |文件编码不是 UTF-8
 | `object quantity error`    |数据条数不为 5000
|  `field quantity error`   |字段数量不为 3 
|  `field name error`       |字段名称不正确 
|  `field value error`      |字段取值不符合要求
