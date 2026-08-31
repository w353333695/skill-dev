package fill_instance

import "testing"

func TestRuleObjectConf_EffectedObject(t *testing.T) {
	type fields struct {
		ObjectId     string
		ObjectIdList []string
	}
	type args struct {
		objectId string
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   bool
	}{
		{
			name: "",
			fields: fields{
				ObjectId: "server",
			},
			args: args{
				objectId: "server",
			},
			want: true,
		},
		{
			name: "",
			fields: fields{
				ObjectIdList: []string{"server"},
			},
			args: args{
				objectId: "server",
			},
			want: true,
		},
		{
			name: "",
			fields: fields{
				ObjectId: "server",
			},
			args: args{
				objectId: "server2",
			},
			want: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := RuleObjectConf{
				ObjectId:     tt.fields.ObjectId,
				ObjectIdList: tt.fields.ObjectIdList,
			}
			if got := c.EffectedObject(tt.args.objectId); got != tt.want {
				t.Errorf("EffectedObject() = %v, want %v", got, tt.want)
			}
		})
	}
}
