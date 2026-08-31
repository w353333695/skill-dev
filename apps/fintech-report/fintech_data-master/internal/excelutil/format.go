package excelutil

import "fmt"

func FloatToRateStr(rate float32) string {
	var rateStr string
	rate = rate * 100
	numInt := int64(rate)
	if float32(numInt) == rate {
		rateStr = fmt.Sprintf("%d", numInt)
	} else if rate < 1 {
		rateStr = fmt.Sprintf("%.2g", rate)
	} else {
		rateStr = fmt.Sprintf("%.2f", rate)
	}
	return rateStr + "%"
}
