package ctxutil

import (
	"context"

	"go.easyops.local/gin-giraffe/pkg/orguser"
	logctx "go.easyops.local/slog/context"
)

func CtxClone(ctx context.Context) context.Context {
	ctxCopy := context.Background()
	orgUser, _ := orguser.FromContext(ctx)
	ctxCopy = orguser.WithUser(ctxCopy, orguser.OrgUser{
		Org:  orgUser.Org,
		User: orgUser.User,
	})

	logger := logctx.MustGetLogger(ctx)
	ctxCopy = logctx.WithLogger(ctxCopy, logger)
	return ctxCopy
}
