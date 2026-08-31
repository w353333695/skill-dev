package arrayutil

import (
	"reflect"
	"testing"
)

func TestInArray(t *testing.T) {
	type args struct {
		arr []string
		str string
	}
	tests := []struct {
		name string
		args args
		want bool
	}{
		{
			"TestInArray1",
			args{
				[]string{"12", "34", "56"},
				"12",
			},
			true,
		},
		{
			"TestInArray2",
			args{
				[]string{"12", "34", "56"},
				"123",
			},
			false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := InArray(tt.args.arr, tt.args.str); got != tt.want {
				t.Errorf("InArray() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_ArraySet(t *testing.T) {
	type args struct {
		arr []string
	}
	tests := []struct {
		name string
		args args
		want []string
	}{
		{
			name: "TestArray",
			args: args{
				arr: []string{"12", "12", "56"},
			},
			want: []string{"12", "56"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ArraySet(tt.args.arr); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ArraySet() = %v, want %v", got, tt.want)
			}
		})
	}
}
