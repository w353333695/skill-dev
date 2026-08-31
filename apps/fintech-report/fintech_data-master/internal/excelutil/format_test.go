package excelutil

import "testing"

func TestFloatToRateStr(t *testing.T) {
	type args struct {
		rate float32
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				rate: 0.2,
			},
			want: "20%",
		},
		{
			name: "",
			args: args{
				rate: 0.002123,
			},
			want: "0.21%",
		},
		{
			name: "",
			args: args{
				rate: 0.2123,
			},
			want: "21.23%",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := FloatToRateStr(tt.args.rate); got != tt.want {
				t.Errorf("FloatToRateStr() = %v, want %v", got, tt.want)
			}
		})
	}
}
