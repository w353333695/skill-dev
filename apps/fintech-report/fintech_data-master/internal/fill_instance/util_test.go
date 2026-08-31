package fill_instance

import "testing"

func TestCompare(t *testing.T) {
	if !CompareEq("one", "one") {
		t.Errorf("equal fail")
	}
	if !CompareNeq("one", "two") {
		t.Errorf("not equal fail")
	}
	if !CompareIn("one", "one") {
		t.Errorf("in fail 1")
	}
	if !CompareIn("one", []string{"one", "two"}) {
		t.Errorf("in fail 2")
	}
	if CompareIn("one", []string{"haha", "two"}) {
		t.Errorf("not in fail 2")
	}
	if !CompareNin("one", []string{"haha", "two"}) {
		t.Errorf("nin fail")
	}
	if CompareNin("one", []string{"one", "two"}) {
		t.Errorf("not nin fail")
	}
	if CompareIsNull("abc") {
		t.Errorf("not null fail")
	}
	if !CompareIsNull(nil) {
		t.Errorf("is null fail")
	}
	if !CompareNotNull("abc") {
		t.Errorf("not null fail")
	}
	if CompareNotNull("") {
		t.Errorf("not null fail")
	}
}
