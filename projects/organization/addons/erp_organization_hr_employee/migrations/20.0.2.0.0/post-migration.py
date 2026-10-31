"""Preserve scope for existing primary and additional organization mappings."""


def migrate(cr, version):
    cr.execute('''
        UPDATE hr_employee AS employee
           SET organization_scope_history = TRUE
         WHERE employee.organization_unit_id IS NOT NULL
            OR EXISTS (
                SELECT 1 FROM erp_employee_organization_assignment AS assignment
                 WHERE assignment.employee_id = employee.id
            )
    ''')
