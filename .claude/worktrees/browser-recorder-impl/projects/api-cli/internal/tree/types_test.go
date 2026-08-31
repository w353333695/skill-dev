package tree

import "testing"

func TestOperationTreeConstruct(t *testing.T) {
	tr := &OperationTree{
		Service: Service{Name: "cmdb", DefaultEndpoint: "backend",
			Endpoints: map[string]*Endpoint{
				"backend": {Name: "backend", BaseURL: "http://x", PathPrefix: "/api/v1", Auth: "backend-sign"},
			}},
		Resources: map[string]*Resource{
			"inst": {Name: "inst", Path: "/instances", Singular: "instance",
				Operations: map[string]*Operation{
					"read": {Verb: "read", Method: "GET", Path: "/{id}",
						Params: []Param{{Name: "id", In: "path", Type: "string", Required: true}}},
				}},
		},
	}
	if tr.Service.Name != "cmdb" {
		t.Fatal("service name mismatch")
	}
	if tr.Resources["inst"].Operations["read"].Method != "GET" {
		t.Fatal("method mismatch")
	}
}
