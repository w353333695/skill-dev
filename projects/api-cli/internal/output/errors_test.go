package output

import "testing"

func TestExitCodeMapping(t *testing.T) {
	if got := ExitCode(nil); got != ExitOK {
		t.Fatal("nil should be OK")
	}
	ae := &APIError{ExitCode: ExitAuthError}
	if got := ExitCode(ae); got != ExitAuthError {
		t.Fatal("auth exit code")
	}
	if got := ExitCode(NormalizeAPIError(401, []byte("no"))); got != ExitAuthError {
		t.Fatalf("401 should map to auth, got %d", got)
	}
}
