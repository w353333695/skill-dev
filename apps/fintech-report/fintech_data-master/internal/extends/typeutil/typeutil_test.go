package typeutil

import (
	"reflect"
	"testing"

	"github.com/gogo/protobuf/proto"
	"github.com/gogo/protobuf/types"

	"go.easyops.local/contracts/protorepo-models/easyops/model/fintech_data"
	"go.easyops.local/kit/gogoprotobuf/protostruct"
)

func TestPbMessageToStruct(t *testing.T) {
	type args struct {
		data proto.Message
	}
	tests := []struct {
		name string
		args args
		want *types.Struct
	}{
		{
			name: "",
			args: args{
				data: &fintech_data.ReportGlobalConfig{
					ClientId:            "fakeId",
					ClientSecret:        "fakeSecret",
					Ip:                  "192.168.100.162",
					Port:                8079,
					FacilityOwnerAgency: "WC001",
					Memo:                "haha",
				},
			},
			want: protostruct.ToStruct(map[string]interface{}{
				"clientId":            "fakeId",
				"clientSecret":        "fakeSecret",
				"ip":                  "192.168.100.162",
				"port":                int64(8079),
				"facilityOwnerAgency": "WC001",
				"memo":                "haha",
			}),
		},
		{
			name: "",
			args: args{
				data: nil,
			},
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := PbMessageToStruct(tt.args.data); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("PbMessageToStruct() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestStructToPbMessage(t *testing.T) {
	type args struct {
		data   *types.Struct
		pbData proto.Message
	}
	tests := []struct {
		name    string
		args    args
		wantErr bool
	}{
		{
			name: "",
			args: args{
				data: protostruct.ToStruct(map[string]interface{}{
					"clientId":     "fakeId",
					"clientSecret": "fakeSecret",
					"ip":           "192.168.100.162",
					"port":         int64(8079),
				}),
				pbData: &fintech_data.ReportGlobalConfig{},
			},
			wantErr: false,
		},
		{
			name: "",
			args: args{
				data: protostruct.ToStruct(map[string]interface{}{
					"clientId":     "fakeId",
					"clientSecret": "fakeSecret",
					"ip":           "192.168.100.162",
					"port":         "xxxx",
				}),
				pbData: &fintech_data.ReportGlobalConfig{},
			},
			wantErr: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if err := StructToPbMessage(tt.args.data, tt.args.pbData); (err != nil) != tt.wantErr {
				t.Errorf("StructToPbMessage() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestPbValueToString(t *testing.T) {
	tests := []struct {
		name string
		val  *types.Value
		want string
	}{
		{
			val:  protostruct.ToValue("123"),
			want: "123",
		},
		{
			val:  protostruct.ToValue(123),
			want: "123",
		},
		{
			val:  protostruct.ToValue(123.3),
			want: "123.3",
		},
		{
			val:  nil,
			want: "null",
		},
		{
			val:  protostruct.ToValue([]string{"1", "2", "3"}),
			want: `["1","2","3"]`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := PbValueToString(tt.val); got != tt.want {
				t.Errorf("PbValueToString() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestIsNullValue(t *testing.T) {
	type args struct {
		value *types.Value
	}
	tests := []struct {
		name string
		args args
		want bool
	}{
		{
			name: "",
			args: args{
				value: nil,
			},
			want: true,
		},
		{
			name: "",
			args: args{
				value: protostruct.ToValue(nil),
			},
			want: true,
		},
		{
			name: "",
			args: args{
				value: protostruct.ToValue(""),
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := IsNullValue(tt.args.value); got != tt.want {
				t.Errorf("IsNullValue() = %v, want %v", got, tt.want)
			}
		})
	}
}
