package apierrors

import (
	"go.easyops.local/kit/gerr"
)

var (
	ErrInvalidArgument    = gerr.NewCode(100000, "ERR_INVALID_ARGUMENT")
	ErrFailedPreCondition = gerr.NewCode(100001, "ERR_FAILED_PRECONDITION")
	ErrOutOfRange         = gerr.NewCode(100002, "ERR_OUT_OF_RANGE")
	ErrUnAuthenticated    = gerr.NewCode(100003, "ERR_UNAUTHENTICATED")
	ErrPermissionDenied   = gerr.NewCode(100004, "ERR_PERMISSION_DENIED")
	ErrNotFound           = gerr.NewCode(100005, "ERR_NOT_FOUND")
	ErrAborted            = gerr.NewCode(100006, "ERR_ABORTED")
	ErrAlreadyExists      = gerr.NewCode(100007, "ERR_ALREADY_EXISTS")
	ErrResourceExhausted  = gerr.NewCode(100008, "ERR_RESOURCE_EXHAUSTED")
	ErrDataLoss           = gerr.NewCode(100009, "ERR_DATA_LOSS")
	ErrUnknown            = gerr.NewCode(100010, "ERR_UNKNOWN")
	ErrInternal           = gerr.NewCode(100011, "ERR_INTERNAL")
	ErrNotImplemented     = gerr.NewCode(100012, "ERR_NOT_IMPLEMENTED")
	ErrUnavailable        = gerr.NewCode(100013, "ERR_UNAVAILABLE")
	ErrDeadlineExceeded   = gerr.NewCode(100014, "ERR_DEADLINE_EXCEEDED")
)

// Client specified an invalid argument. Check error message and error details for more information.
func NewErrorInvalidArgument(message string) gerr.ApiStatus {
	return gerr.BadRequest(ErrInvalidArgument).Message(message).Build()
}

// Request can not be executed in the current system state, such as deleting a non-empty directory.
func NewErrorFailedPreCondition(message string) gerr.ApiStatus {
	return gerr.BadRequest(ErrFailedPreCondition).Message(message).Build()
}

// Client specified an invalid range.
func NewErrorOutOfRange(message string) gerr.ApiStatus {
	return gerr.BadRequest(ErrOutOfRange).Message(message).Build()
}

// Request not authenticated due to missing, invalid, or expired OAuth token.
func NewErrorUnAuthenticated(message string) gerr.ApiStatus {
	return gerr.Unauthorized(ErrUnAuthenticated).Message(message).Build()
}

// Client does not have sufficient permission.
// This can happen because the OAuth token does not have the right scopes,
// the client doesn't have permission, or the API has not been enabled for the client project.
func NewErrorPermissionDenied(message string) gerr.ApiStatus {
	return gerr.Forbidden(ErrPermissionDenied).Message(message).Build()
}

// A specified resource is not found, or the request is rejected by undisclosed reasons, such as whitelisting.
func NewErrorNotFound(message string) gerr.ApiStatus {
	return gerr.NotFound(ErrNotFound).Message(message).Build()
}

// Concurrency conflict, such as read-modify-write conflict.
func NewErrorAborted(message string) gerr.ApiStatus {
	return gerr.Conflict(ErrAborted).Message(message).Build()
}

// The resource that a client tried to create already exists.
func NewErrorAlreadyExists(message string) gerr.ApiStatus {
	return gerr.Conflict(ErrAlreadyExists).Message(message).Build()
}

// Either out of resource quota or reaching rate limiting.
// The client should look for google.rpc.QuotaFailure error detail for more information.
func NewErrorResourceExhausted(message string) gerr.ApiStatus {
	return gerr.TooManyRequests(ErrResourceExhausted).Message(message).Build()
}

// Unrecoverable data loss or data corruption. The client should report the error to the user.
func NewErrorErrDataLoss(message string) gerr.ApiStatus {
	return gerr.InternalServerError(ErrDataLoss).Message(message).Build()
}

// Unknown server error. Typically a server bug.
func NewErrorUnknown(message string) gerr.ApiStatus {
	return gerr.InternalServerError(ErrUnknown).Message(message).Build()
}

// Internal server error. Typically a server bug.
func NewErrorInternal(message string) gerr.ApiStatus {
	return gerr.InternalServerError(ErrInternal).Message(message).Build()
}

// API method not implemented by the server.
func NewErrorNotImplemented(message string) gerr.ApiStatus {
	return gerr.NotImplemented(ErrNotImplemented).Message(message).Build()
}

// Service unavailable. Typically the server is down.
func NewErrorUnAvailable(message string) gerr.ApiStatus {
	return gerr.ServiceUnavailable(ErrUnavailable).Message(message).Build()
}

// Request deadline exceeded.
// This will happen only if the caller sets a deadline that is shorter than the method's default deadline
// (i.e. requested deadline is not enough for the server to process the request)
// and the request did not finish within the deadline.
func NewErrorDeadlineExceeded(message string) gerr.ApiStatus {
	return gerr.GatewayTimeout(ErrDeadlineExceeded).Message(message).Build()
}

// Client specified an invalid argument. Check error message and error details for more information.
func InvalidArgumentErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.BadRequest(ErrInvalidArgument).Messagef(format, args...).Build()
}

// Request can not be executed in the current system state, such as deleting a non-empty directory.
func FailedPreConditionErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.BadRequest(ErrFailedPreCondition).Messagef(format, args...).Build()
}

// Client specified an invalid range.
func OutOfRangeErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.BadRequest(ErrOutOfRange).Messagef(format, args...).Build()
}

// Request not authenticated due to missing, invalid, or expired OAuth token.
func UnAuthenticatedErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.Unauthorized(ErrUnAuthenticated).Messagef(format, args...).Build()
}

// Client does not have sufficient permission.
// This can happen because the OAuth token does not have the right scopes,
// the client doesn't have permission, or the API has not been enabled for the client project.
func PermissionDeniedErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.Forbidden(ErrPermissionDenied).Messagef(format, args...).Build()
}

// A specified resource is not found, or the request is rejected by undisclosed reasons, such as whitelisting.
func NotFoundErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.NotFound(ErrNotFound).Messagef(format, args...).Build()
}

// Concurrency conflict, such as read-modify-write conflict.
func AbortedErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.Conflict(ErrAborted).Messagef(format, args...).Build()
}

// The resource that a client tried to create already exists.
func AlreadyExistsErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.Conflict(ErrAlreadyExists).Messagef(format, args...).Build()
}

// Either out of resource quota or reaching rate limiting.
// The client should look for google.rpc.QuotaFailure error detail for more information.
func ResourceExhaustedErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.TooManyRequests(ErrResourceExhausted).Messagef(format, args...).Build()
}

// Unrecoverable data loss or data corruption. The client should report the error to the user.
func ErrDataLossErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.InternalServerError(ErrDataLoss).Messagef(format, args...).Build()
}

// Unknown server error. Typically a server bug.
func UnknownErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.InternalServerError(ErrUnknown).Messagef(format, args...).Build()
}

// Internal server error. Typically a server bug.
func InternalErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.InternalServerError(ErrInternal).Messagef(format, args...).Build()
}

// API method not implemented by the server.
func NotImplementedErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.NotImplemented(ErrNotImplemented).Messagef(format, args...).Build()
}

// Service unavailable. Typically the server is down.
func UnAvailableErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.ServiceUnavailable(ErrUnavailable).Messagef(format, args...).Build()
}

// Request deadline exceeded.
// This will happen only if the caller sets a deadline that is shorter than the method's default deadline
// (i.e. requested deadline is not enough for the server to process the request)
// and the request did not finish within the deadline.
func DeadlineExceededErrorf(format string, args ...interface{}) gerr.ApiStatus {
	return gerr.GatewayTimeout(ErrDeadlineExceeded).Messagef(format, args...).Build()
}
