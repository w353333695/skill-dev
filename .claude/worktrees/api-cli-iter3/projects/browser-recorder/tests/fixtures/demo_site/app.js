// tests/fixtures/demo_site/app.js
// 中性演示 JS：登录后跳列表；搜索触发模拟 XHR 返回 JSON。
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('login-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      // 演示：任意输入都"登录成功"
      localStorage.setItem('demo_user', document.getElementById('username').value);
      window.location.href = 'list.html';
    });
    return;
  }
  var btn = document.getElementById('search-btn');
  var input = document.getElementById('search');
  var list = document.getElementById('list');
  function doSearch() {
    var q = input.value || '';
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'data.json?q=' + encodeURIComponent(q), true);
    xhr.onload = function () {
      try {
        var data = JSON.parse(xhr.responseText);
        list.innerHTML = '';
        (data.items || []).forEach(function (it) {
          var li = document.createElement('li');
          li.textContent = it.name + ' (' + it.id + ')';
          list.appendChild(li);
        });
      } catch (e) {}
    };
    xhr.send();
  }
  if (btn) btn.addEventListener('click', doSearch);
});
