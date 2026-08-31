package ctxutil

import (
	"context"
	"testing"

	"go.easyops.local/gin-giraffe/pkg/orguser"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestCtxClone(t *testing.T) {
	ctx := logctx.WithLogger(context.Background(), slog.Noop())
	ctx = orguser.WithUser(ctx, orguser.OrgUser{Org: 8888, User: "easyops"})
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name string
		args args
		want context.Context
	}{
		{
			name: "",
			args: args{
				ctx: ctx,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			CtxClone(tt.args.ctx)
		})
	}
}
