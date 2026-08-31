package fill_instance

import (
	"reflect"

	funk "github.com/thoas/go-funk"
)

func CompareEq(v1, v2 interface{}) bool {
	return reflect.DeepEqual(v1, v2)
}

func CompareNeq(v1, v2 interface{}) bool {
	return !CompareEq(v1, v2)
}

func CompareIn(v1, v2 interface{}) bool {
	return funk.Contains(v2, v1)
}

func CompareNin(v1, v2 interface{}) bool {
	a := !CompareIn(v1, v2)
	return a
}

func CompareIsNull(v1 interface{}) bool {
	if v1 == nil || v1 == "" {
		return true
	}
	return false
}

func CompareNotNull(v1 interface{}) bool {
	return !CompareIsNull(v1)
}
