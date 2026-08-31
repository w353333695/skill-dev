package report_task

import (
	"context"
	"fmt"
	"reflect"
	"testing"

	"github.com/easyops-cn/mongo-driver-helper/pmongo"
	"github.com/golang/mock/gomock"

	"go.easyops.local/fintech_data/internal/history"
	"go.easyops.local/fintech_data/internal/timer"
	history2 "go.easyops.local/fintech_data/mock/history"
	"go.easyops.local/slog"
	logctx "go.easyops.local/slog/context"
)

func TestNewRecordJobManager(t *testing.T) {
	type args struct {
		centerData      history.CenterData
		historyRecorder history.Recorder
		mongoClient     pmongo.ClientInterface
	}
	tests := []struct {
		name string
		args args
		want timer.JobManager
	}{
		{
			name: "",
			args: args{},
			want: &recordJobManager{},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := NewRecordJobManager(tt.args.centerData, tt.args.historyRecorder, tt.args.mongoClient); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("NewRecordJobManager() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_recordJobManager_Do(t *testing.T) {
	ctrl := gomock.NewController(t)
	defer ctrl.Finish()

	ctx := context.Background()
	ctx = logctx.WithLogger(ctx, slog.Noop())
	type fields struct {
		centerData      history.CenterData
		historyRecorder history.Recorder
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		wantErr bool

		aggregateErr error
		recordErr    error
	}{
		{
			name: "",
			args: args{
				ctx: ctx,
			},
			wantErr: false,
		},
		{
			name: "",
			args: args{
				ctx: ctx,
			},
			aggregateErr: fmt.Errorf("mock fail"),
			wantErr:      true,
		},
		{
			name: "",
			args: args{
				ctx: ctx,
			},
			recordErr: fmt.Errorf("mock fail"),
			wantErr:   true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			centerDataMock := history2.NewMockCenterData(ctrl)
			recorderMock := history2.NewMockRecorder(ctrl)
			r := recordJobManager{
				centerData:      centerDataMock,
				historyRecorder: recorderMock,
			}
			centerDataMock.EXPECT().Aggregate(gomock.Any(), r.makeQuery(), gomock.Any()).DoAndReturn(
				func(ctx context.Context, pipeline interface{}, result interface{}) error {
					resultCount := result.(*[]objCount)
					resultCount1 := []objCount{{Id: "server", Total: 10}}
					*resultCount = resultCount1
					return tt.aggregateErr
				}).Times(1)
			if tt.aggregateErr == nil {
				recorderMock.EXPECT().Save(gomock.Any(), []history.ReportCount{{Total: 10, ObjectId: "server", InstanceId: "record_job", TaskId: "record_job"}}).Return(tt.recordErr).Times(1)
			}
			if err := r.Do(tt.args.ctx); (err != nil) != tt.wantErr {
				t.Errorf("Do() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func Test_recordJobManager_GetJobName(t *testing.T) {
	type fields struct {
		centerData      history.CenterData
		historyRecorder history.Recorder
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name:   "",
			fields: fields{},
			want:   "record_job",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := recordJobManager{
				centerData:      tt.fields.centerData,
				historyRecorder: tt.fields.historyRecorder,
			}
			if got := r.GetJobName(); got != tt.want {
				t.Errorf("GetJobName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_recordJobManager_GetLockName(t *testing.T) {
	type fields struct {
		centerData      history.CenterData
		historyRecorder history.Recorder
	}
	type args struct {
		org int
	}
	tests := []struct {
		name   string
		fields fields
		args   args
		want   string
	}{
		{
			name:   "",
			fields: fields{},
			args: args{
				org: 8888,
			},
			want: "fintech:report:record:8888:record_job",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := recordJobManager{
				centerData:      tt.fields.centerData,
				historyRecorder: tt.fields.historyRecorder,
			}
			if got := r.GetLockName(tt.args.org); got != tt.want {
				t.Errorf("GetLockName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_recordJobManager_GetName(t *testing.T) {
	type fields struct {
		centerData      history.CenterData
		historyRecorder history.Recorder
	}
	tests := []struct {
		name   string
		fields fields
		want   string
	}{
		{
			name:   "",
			fields: fields{},
			want:   "record_task",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := recordJobManager{
				centerData:      tt.fields.centerData,
				historyRecorder: tt.fields.historyRecorder,
			}
			if got := r.GetName(); got != tt.want {
				t.Errorf("GetName() = %v, want %v", got, tt.want)
			}
		})
	}
}

func Test_recordJobManager_ListJob(t *testing.T) {
	type fields struct {
		centerData      history.CenterData
		historyRecorder history.Recorder
	}
	type args struct {
		ctx context.Context
	}
	tests := []struct {
		name    string
		fields  fields
		args    args
		want    []timer.Job
		wantErr bool
	}{
		{
			name: "",
			fields: fields{
				centerData:      nil,
				historyRecorder: nil,
			},
			args: args{},
			want: []timer.Job{
				recordJobManager{},
			},
			wantErr: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := recordJobManager{
				centerData:      tt.fields.centerData,
				historyRecorder: tt.fields.historyRecorder,
			}
			got, err := r.ListJob(tt.args.ctx)
			if (err != nil) != tt.wantErr {
				t.Errorf("ListJob() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ListJob() got = %v, want %v", got, tt.want)
			}
		})
	}
}
