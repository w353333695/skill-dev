package report_task

// 批次的相关统计信息， 以中信的批次为维度
type batchCountStatics struct {
	Inserted int
	Removed  int
	Updated  int
	Failed   int
}
