# OdooCC 微信登录验收清单

`occ_wechat_login_test` 是 `occ_wechat_login` 的人工验收辅助模块。它把上线前需要用真实微信、真实回调和真实邮件链路完成的检查整理为管理员清单，不参与认证流程本身。

## English summary

`occ_wechat_login_test` provides an administrator-only manual acceptance checklist for `occ_wechat_login`. It records four-state results and sanitized notes for real WeChat, callback, email verification, repeat login, account binding, and user-type checks. It stores no credentials or WeChat identity values and adds no mock login, bypass, or authentication backdoor.

Dependency-free manifest metadata allows an optional deployment aggregator to organize the
existing administrator menu while this module remains independently installable.

## 功能边界

- 提供配置、扫码、首次开户、邮箱验证、再次登录、账号绑定和用户类型七类验收样例。
- 每项可标记为“待验收”“通过”“失败”或“阻塞”，并填写脱敏备注。
- 在清单列表、表单和设置菜单中提供“前往微信登录配置”快捷入口。
- 只有系统管理员组可以查看和维护清单。
- 不保存 AppID、AppSecret、密码、Token、微信授权码、验证链接、UnionID、OpenID 或完整邮箱。
- 不注册登录路由，不调用微信接口，不提供模拟扫码、伪造身份、跳过验证或其他认证后门。

备注字段是自由文本，只应用于脱敏结论。管理员不得将凭据、完整个人身份标识、邮件原文、验证链接或包含敏感参数的截图粘贴到清单中。

## 安装

1. 先安装并配置正式模块 `occ_wechat_login`。
2. 更新应用列表，安装 `OdooCC 微信登录验收清单`。
3. 以系统管理员进入“设置 → 微信登录验收 → 验收清单”。
4. 使用“前往微信登录配置”进入“常规设置 → 集成 → OdooCC 微信登录”。

模块版本为 `19.0.1.0.1`，不会自动安装。

本模块用于预发布或与生产等价的专用验收数据库，不建议在生产数据库中安装。若业务必须在生产环境执行最终真机检查，应先完成安全评审，只短期安装，并在留存必要的脱敏验收结论后卸载。

## 统一演示入口协议

本模块始终可以单独安装，不依赖、不导入部署侧的 `occ_odoocc_demo`。Manifest 中的
`odoocc_demo` 是版本化的纯数据协议，供 OdooCC 在线演示环境自动发现并组织菜单：

- 分类：`collaboration_integration`（协同与平台集成）；
- 可被接管的模块菜单：`occ_wechat_login_test.menu_occ_wechat_login_acceptance_root`；
- 默认可点击入口：`occ_wechat_login_test.menu_occ_wechat_login_acceptance_check`。

未安装聚合模块时，验收入口仍位于“设置”。聚合环境只允许重组菜单，不得改变
`base.group_system` 的菜单限制和模型 ACL；因此普通内部用户不会因为安装聚合模块而看到
或读取本验收清单。

## 真实验收原则

1. 使用已审核的微信开放平台网站应用、HTTPS 域名和生产等价反向代理配置。
2. 使用真实微信扫描页面生成的二维码，不手工构造 callback、state、grant、UnionID 或 OpenID。
3. 使用专用验收邮箱检查验证邮件、首次凭据邮件和标准密码登录。
4. 首次开户、重复绑定、门户用户和内部用户场景需要使用相应的未绑定真实微信账号，不通过数据库改身份字段来复用账号。
5. 只在备注中记录脱敏现象，例如“验证邮件延迟约两分钟”或“门户用户无法进入后台”；不要记录实际账号和凭据。

样例数据使用 `noupdate` 加载，模块升级不会覆盖已经填写的验收状态和备注。管理员也可以创建部署专属的补充检查项；自动测试只验证样例仍存在且分类完整，不会把已经完成的人工状态重置为“待验收”。

## 自动测试范围

自动测试只验证本辅助模块自身：

- 七类固定样例是否存在且分类完整（不覆盖人工填写的状态和备注）；
- 四种状态和备注是否可写；
- 模型是否没有凭据或微信身份字段；
- 是否只有系统管理员拥有模型 ACL；
- 配置快捷入口是否打开正式模块所在的常规设置表单。

自动测试不会模拟微信授权，也不能替代真机验收。可在包含本仓库 addons 路径的 Odoo 19 环境运行：

```bash
./odoo-bin -d <test_database> -i occ_wechat_login_test \
    --test-enable --test-tags /occ_wechat_login_test --stop-after-init
```

## 许可证与联系

- License: AGPL-3
- Author: Odoo老赵
- Website: <https://odoocc.com>
- Support: <156277468@qq.com>
