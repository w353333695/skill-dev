package stringutil

import "strings"

// 先只支持前缀或后缀匹配 %xx、xx%
func FuzzyMatch(pattern string, value string) bool {
	if strings.HasPrefix(pattern, "%") {
		pattern = strings.ReplaceAll(pattern, "%", "")
		return strings.HasSuffix(value, pattern)
	} else if strings.HasSuffix(pattern, "%") {
		pattern = strings.ReplaceAll(pattern, "%", "")
		return strings.HasPrefix(value, pattern)
	}
	return pattern == value
}
