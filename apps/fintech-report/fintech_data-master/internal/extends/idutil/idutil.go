package idutil

import (
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"github.com/segmentio/ksuid"
)

func Guid() string {
	hashMd5 := md5.New()
	hashMd5.Write([]byte(fmt.Sprintf("%s%d", ksuid.New().String(), time.Now().Unix())))
	str := hex.EncodeToString(hashMd5.Sum(nil))
	return strings.ToLower(str)
}
