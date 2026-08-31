package cmdbutil

import (
	"testing"

	pbtypes "github.com/gogo/protobuf/types"

	"go.easyops.local/kit/gogoprotobuf/protostruct"
)

func TestGetInstanceId(t *testing.T) {
	type args struct {
		instanceData *pbtypes.Struct
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				instanceData: protostruct.ToStruct(map[string]interface{}{"instanceId": "aaa"}),
			},
			want: "aaa",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetInstanceId(tt.args.instanceData); got != tt.want {
				t.Errorf("GetInstanceId() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetShowName(t *testing.T) {
	type args struct {
		instanceData *pbtypes.Struct
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				instanceData: protostruct.ToStruct(map[string]interface{}{"#showKey": []string{"aaa"}}),
			},
			want: "aaa",
		},
		{
			name: "",
			args: args{
				instanceData: protostruct.ToStruct(map[string]interface{}{"#showKey": []string{"aaa", "bbb"}}),
			},
			want: "aaa(bbb)",
		},
		{
			name: "",
			args: args{
				instanceData: protostruct.ToStruct(map[string]interface{}{"#showKey": []string{}}),
			},
			want: "",
		},
		{
			name: "",
			args: args{
				instanceData: protostruct.ToStruct(map[string]interface{}{"instanceId": "ddd"}),
			},
			want: "ddd",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetShowName(tt.args.instanceData); got != tt.want {
				t.Errorf("GetShowName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetInstanceIdByMap(t *testing.T) {
	type args struct {
		instanceData map[string]interface{}
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "",
			args: args{
				instanceData: map[string]interface{}{
					"instanceId": "id1",
				},
			},
			want: "id1",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetInstanceIdByMap(tt.args.instanceData); got != tt.want {
				t.Errorf("GetInstanceIdByMap() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetCreator(t *testing.T) {
	type args struct {
		instanceData *pbtypes.Struct
	}
	tests := []struct {
		name string
		args args
		want string
	}{
		{
			name: "Field exists with value",
			args: args{
				instanceData: &pbtypes.Struct{
					Fields: map[string]*pbtypes.Value{
						"creator": &pbtypes.Value{
							Kind: &pbtypes.Value_StringValue{
								StringValue: "John Doe",
							},
						},
					},
				},
			},
			want: "John Doe",
		},
		{
			name: "Field does not exist",
			args: args{
				instanceData: &pbtypes.Struct{
					Fields: map[string]*pbtypes.Value{},
				},
			},
			want: "",
		},
		{
			name: "Field exists but empty",
			args: args{
				instanceData: &pbtypes.Struct{
					Fields: map[string]*pbtypes.Value{
						"creator": &pbtypes.Value{
							Kind: &pbtypes.Value_StringValue{
								StringValue: "",
							},
						},
					},
				},
			},
			want: "",
		},
		{
			name: "Field exists with non-empty value",
			args: args{
				instanceData: &pbtypes.Struct{
					Fields: map[string]*pbtypes.Value{
						"creator": &pbtypes.Value{
							Kind: &pbtypes.Value_StringValue{
								StringValue: "Alice",
							},
						},
					},
				},
			},
			want: "Alice",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetCreator(tt.args.instanceData); got != tt.want {
				t.Errorf("GetCreator() = %v, want %v", got, tt.want)
			}
		})
	}
}
