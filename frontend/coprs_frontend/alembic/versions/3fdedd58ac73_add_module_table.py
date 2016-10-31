"""add module table

Revision ID: 3fdedd58ac73
Revises: 414a86b37a0f
Create Date: 2016-10-26 22:01:09.361070

"""

# revision identifiers, used by Alembic.
revision = '3fdedd58ac73'
down_revision = '414a86b37a0f'

from alembic import op
import sqlalchemy as sa

from coprs.models import Module, Action, Copr, User, Group
from sqlalchemy.orm import sessionmaker

import json
import base64
import modulemd
from coprs.logic.coprs_logic import CoprsLogic
from coprs.logic.actions_logic import ActionsLogic
from coprs.helpers import ActionTypeEnum


def upgrade():
    bind = op.get_bind()
    Session = sessionmaker()
    session = Session(bind=bind)

    # Table schema is defined in the `Module` model, so the actual table can
    # be created with only this one line
    Module.__table__.create(bind)
    session.commit()

    # Now, let's seed the table with existing modules which are violently stored in the `action` table
    added_modules = set()
    for action in ActionsLogic.get_many(ActionTypeEnum("build_module")).order_by(Action.id.desc()):
        data = json.loads(action.data)
        copr = get_copr(session, data["ownername"], data["projectname"])
        yaml = base64.b64decode(data["modulemd_b64"])
        mmd = modulemd.ModuleMetadata()
        mmd.loads(yaml)

        module_kwargs = {
            "name": mmd.name,
            "version": mmd.version,
            "release": mmd.release,
            "summary": mmd.summary,
            "description": mmd.description,
            "yaml_b64": data["modulemd_b64"],
            "created_on": action.created_on,

            "copr_id": copr.id,
            "user_id": copr.user_id,
        }

        # There is no constraint for currently existing modules, but in new table, there
        # must be unique user/nvr. Therefore in the case of duplicit modules,
        # we will add only the newest one
        if full_module_name(mmd, copr.owner_name) in added_modules:
            print("Skipping {}; Already exists".format(full_module_name(mmd, copr.owner_name)))
            continue

        session.add(Module(**module_kwargs))
        added_modules.add(full_module_name(mmd, copr.owner_name))


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('module')
    ### end Alembic commands ###


def full_module_name(mmd, ownername):
    return "{}/{}-{}-{}".format(ownername, mmd.name, mmd.version, mmd.release)


def get_copr(session, ownername, projectname):
    if ownername[0] == "@":
        coprs = CoprsLogic.filter_by_group_name(session.query(Copr), ownername[1:])
    else:
        coprs = CoprsLogic.filter_by_user_name(session.query(Copr), ownername)
    return CoprsLogic.filter_by_name(coprs, projectname).first()
