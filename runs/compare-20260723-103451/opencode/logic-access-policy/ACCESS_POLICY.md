# 订单访问策略

- `draft` 状态：`editor` 可查看和编辑；`reviewer` 只能查看；`admin` 可查看、
  编辑、删除。
- `submitted` 状态：`editor` 仅可查看，不可编辑；`reviewer` 可查看和编辑
  （用于审核修改）；`admin` 可查看、编辑、删除。
- `archived` 状态：仅 `admin` 可查看；其他角色不可查看、不可编辑、不可删除。
