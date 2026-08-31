package idutil

import "testing"

func TestGuid(t *testing.T) {
	tests := []struct {
		name string
		want string
	}{
		{
			name: "normal",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			Guid()
		})
	}
}
