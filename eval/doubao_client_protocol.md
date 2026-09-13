# 豆包视觉 OCR V2：客户端评测协议

## 运行方式

每张图片新建一个对话，只上传一张票据，并把下方提示词中的 `INV-XX` 替换为该图片对应的匿名编号。不要在同一对话中上传多张图片，避免模型利用其他样本信息。

## 固定提示词

```text
你是财务票据字段提取器。只根据当前上传图片读取字段，不查询外部资料，不推测被遮挡或模糊内容。

请提取：
1. 发票号码 invoice_number：只保留数字；无法确认则为空字符串。
2. 开票日期 issue_date：格式 YYYY-MM-DD；无法确认则为空字符串。
3. 价税合计 total_amount：只保留两位小数，不带货币符号；无法确认则为空字符串。

逐字符检查发票号码；不要补位、删位或根据常见长度猜测。只输出一个合法 JSON 对象，不要 Markdown，不要解释：
{"alias":"INV-XX","invoice_number":"","issue_date":"","total_amount":"","uncertain_fields":[]}

uncertain_fields 只能包含 invoice_number、issue_date、total_amount。任一字段模糊、被遮挡或你不能逐字符确认时，将字段名加入 uncertain_fields，并把对应值设为空字符串。
```

## 保存结果

将 5 次返回的 JSON 对象按匿名编号依次放入一个 JSON 数组，保存到私有目录：

`work/invoice-audit/doubao_client_predictions_private.json`

不要把票据图片、真实号码或该结果文件提交到 GitHub。

## 公开内容范围

这是“豆包客户端人工触发的视觉模型基线”，不是 API 集成，也不是自动化生产链路。公开报告只展示样本量、字段正确数、转人工数和错误类型，不展示真实字段值。
