package stringutil

import "testing"

func TestFuzzyMatch(t *testing.T) {
	type args struct {
		pattern string
		value   string
	}
	tests := []struct {
		name string
		args args
		want bool
	}{
		{
			name: "",
			args: args{
				pattern: "server_%",
				value:   "server_deployment",
			},
			want: true,
		},
		{
			name: "",
			args: args{
				pattern: "%_deployment",
				value:   "server_deployment",
			},
			want: true,
		},
		{
			name: "",
			args: args{
				pattern: "server_deployment",
				value:   "server_deployment",
			},
			want: true,
		},
		{
			name: "",
			args: args{
				pattern: "%_deployment",
				value:   "server_deployment2",
			},
			want: false,
		},
		{
			name: "",
			args: args{
				pattern: "server_%",
				value:   "serv2er_deployment",
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := FuzzyMatch(tt.args.pattern, tt.args.value); got != tt.want {
				t.Errorf("FuzzyMatch() = %v, want %v", got, tt.want)
			}
		})
	}
}
