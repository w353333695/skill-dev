package timeutil

import "time"

type NowTimeFunc func() time.Time

var TimeZone = time.FixedZone("CST", 8*3600)

const TimeFormat = "2006-01-02 15:04:05"

func NowTime() time.Time {
	return time.Now().In(TimeZone)
}

func Today() time.Time {
	year, month, day := NowTime().Date()
	return time.Date(year, month, day, 0, 0, 0, 0, TimeZone)
}

func GetDateTimeByTime(t time.Time) time.Time {
	year, month, day := t.Date()
	return time.Date(year, month, day, 0, 0, 0, 0, TimeZone)
}

func ParseTimeStr(timeStr string) (time.Time, error) {
	return time.ParseInLocation(TimeFormat, timeStr, TimeZone)
}

func ParseTimeStrToUnix(timeStr string) (int64, error) {
	tm, err := ParseTimeStr(timeStr)
	if err != nil {
		return 0, err
	}
	return tm.Unix(), nil
}

func DefaultTimeLimit(timeFunc NowTimeFunc, dayBack int) (int, int) {
	et := timeFunc()
	st := et.AddDate(0, 0, -dayBack)
	return int(st.Unix()), int(et.Unix())
}
