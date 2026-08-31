package arrayutil

func InArray(arr []string, str string) bool {
	for _, v := range arr {
		if v == str {
			return true
		}
	}
	return false
}

func ArraySet(arr []string) []string {
	var result []string
	flag := make(map[string]struct{})
	for _, v := range arr {
		if _, ok := flag[v]; !ok {
			result = append(result, v)
			flag[v] = struct{}{}
		}
	}
	return result
}
