package monitor_kits

import (
	"bytes"
	"fmt"
	"os"
	"strings"
	"testing"
	"text/template"
)

func TestGenericSwitchPortFallback(testContext *testing.T) {
	content, err := os.ReadFile("../../monitor-kits/generic-switch-monitoring/config.template.yaml")
	if err != nil {
		testContext.Fatal(err)
	}
	parsed, err := template.New("switch").Funcs(template.FuncMap{"add1": func(value int) int { return value + 1 }}).Parse(string(content))
	if err != nil {
		testContext.Fatal(err)
	}
	cases := []struct {
		name string
		port interface{}
		want string
	}{
		{"null", "null", "161"}, {"nil", nil, "161"}, {"empty", "", "161"},
		{"default", "161", "161"}, {"custom", "1161", "1161"}, {"number", 1161, "1161"},
		{"invalid", "invalid", "invalid"},
	}
	for _, brand := range []string{"Cisco", "Huawei", "H3C", "VRP", "Gigamon", "Ruijie", "Digital China", "unknown"} {
		for _, testCase := range cases {
			testContext.Run(brand+"/"+testCase.name, func(testContext *testing.T) {
				params := map[string]interface{}{"snmpIp": "192.0.2.10", "snmpPort": testCase.port, "brand": brand, "interface_names": []string{"Ethernet1", "Ethernet2"}}
				var rendered bytes.Buffer
				if err := parsed.Execute(&rendered, params); err != nil {
					testContext.Fatal(err)
				}
				want := fmt.Sprintf(`hosts: [ "192.0.2.10:%s" ]`, testCase.want)
				if !strings.Contains(rendered.String(), want) {
					testContext.Fatalf("未生成预期的目标 %s", want)
				}
			})
		}
	}
	var missing bytes.Buffer
	if err := parsed.Execute(&missing, map[string]interface{}{"snmpIp": "192.0.2.10", "brand": "H3C", "interface_names": []string{}}); err != nil {
		testContext.Fatal(err)
	}
	if !strings.Contains(missing.String(), `hosts: [ "192.0.2.10:161" ]`) {
		testContext.Fatal("缺失端口未降级为161")
	}
}
