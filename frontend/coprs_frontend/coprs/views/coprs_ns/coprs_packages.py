import flask
import json

from flask import Response, stream_with_context, url_for
from flask import send_file
from coprs import db
from coprs import forms
from coprs import helpers
from coprs.views.coprs_ns import coprs_ns
from coprs.views.coprs_ns.coprs_builds import render_add_build_scm, render_add_build_pypi, render_add_build_custom
from coprs.views.misc import login_required, page_not_found, req_with_copr, req_with_copr, send_build_icon
from coprs.logic.complex_logic import ComplexLogic
from coprs.logic.packages_logic import PackagesLogic
from coprs.logic.users_logic import UsersLogic
from coprs.exceptions import (ActionInProgressException,ObjectNotFound, NoPackageSourceException,
                              InsufficientRightsException,UnknownSourceTypeException,MalformedArgumentException)


@coprs_ns.route("/<username>/<coprname>/packages/")
@coprs_ns.route("/g/<group_name>/<coprname>/packages/")
@req_with_copr
def copr_packages(copr):
    packages_query = PackagesLogic.get_copr_packages_list(copr)
    return flask.Response(stream_with_context(helpers.stream_template("coprs/detail/packages.html",
                                 copr=copr,
                                 packages=list(packages_query))))

@coprs_ns.route("/<username>/<coprname>/package/<package_name>/")
@coprs_ns.route("/g/<group_name>/<coprname>/package/<package_name>/")
@req_with_copr
def copr_package(copr, package_name):
    package = ComplexLogic.get_package_safe(copr, package_name)
    return flask.render_template("coprs/detail/package.html", package=package, copr=copr)

@coprs_ns.route("/<username>/<coprname>/package/<package_name>/status_image/last_build.png")
@coprs_ns.route("/g/<group_name>/<coprname>/package/<package_name>/status_image/last_build.png")
@req_with_copr
def copr_package_icon(copr, package_name):
    try:
        package = ComplexLogic.get_package_safe(copr, package_name)
    except ObjectNotFound:
        return send_file("static/status_images/bad_url.png", mimetype='image/png')

    return send_build_icon(package.last_build())


@coprs_ns.route("/<username>/<coprname>/packages/rebuild-all/", methods=["GET", "POST"])
@coprs_ns.route("/g/<group_name>/<coprname>/packages/rebuild-all/", methods=["GET", "POST"])
@req_with_copr
def copr_rebuild_all_packages(copr):
    form = forms.RebuildAllPackagesFormFactory(
        copr.active_chroots, [package.name for package in copr.packages])()

    if flask.request.method == "POST" and form.validate_on_submit():
        try:
            packages = []
            for package_name in form.packages.data:
                packages.append(ComplexLogic.get_package_safe(copr, package_name))

            PackagesLogic.batch_build(
                flask.g.user,
                copr,
                packages,
                form.selected_chroots,
                enable_net=form.enable_net.data)

        except (ObjectNotFound, ActionInProgressException, NoPackageSourceException, \
                InsufficientRightsException, MalformedArgumentException) as e:
            db.session.rollback()
            flask.flash(str(e), "error")
        else:
            db.session.commit()
            flask.flash("Batch build successfully started.", "success")
            return flask.redirect(helpers.url_for_copr_builds(copr))

    return flask.render_template(
        "coprs/detail/packages_rebuild_all.html",
        view="coprs_ns.copr_rebuild_all_packages",
        form=form, copr=copr)


@coprs_ns.route("/<username>/<coprname>/package/<package_name>/rebuild")
@coprs_ns.route("/g/<group_name>/<coprname>/package/<package_name>/rebuild")
@req_with_copr
def copr_rebuild_package(copr, package_name):
    package = ComplexLogic.get_package_safe(copr, package_name)
    data = package.source_json_dict

    if package.source_type_text == "scm":
        form = forms.BuildFormScmFactory
        f = render_add_build_scm
        view_suffix = "_scm"
    elif package.source_type_text == "pypi":
        form = forms.BuildFormPyPIFactory
        f = render_add_build_pypi
        view_suffix = "_pypi"
    elif package.source_type_text == "custom":
        form = forms.BuildFormCustomFactory
        f = render_add_build_custom
        view_suffix = "_custom"
    else:
        flask.flash("Package {} has not the default source which is required for rebuild. Please configure some source"
                    .format(package_name, copr.full_name))
        return flask.redirect(helpers.copr_url("coprs_ns.copr_edit_package", copr, package_name=package_name))

    form = form(copr.active_chroots)(data=data)
    return f(copr, form, view="coprs_ns.copr_new_build" + view_suffix, package=package)


@coprs_ns.route("/<username>/<coprname>/package/add")
@coprs_ns.route("/<username>/<coprname>/package/add/<source_type_text>")
@coprs_ns.route("/g/<group_name>/<coprname>/package/add")
@coprs_ns.route("/g/<group_name>/<coprname>/package/add/<source_type_text>")
@login_required
@req_with_copr
def copr_add_package(copr, source_type_text="scm", **kwargs):
    form = {
        "scm": forms.PackageFormScm(),
        "pypi": forms.PackageFormPyPI(),
        "rubygems": forms.PackageFormRubyGems(),
        "custom": forms.PackageFormCustom(),
    }

    if "form" in kwargs:
        form[source_type_text] = kwargs["form"]

    return flask.render_template("coprs/detail/add_package.html", copr=copr, package=None,
                                 source_type_text=source_type_text, view="coprs_ns.copr_new_package",
                                 form_scm=form["scm"], form_pypi=form["pypi"],
                                 form_rubygems=form["rubygems"],
                                 form_custom=form['custom'])


@coprs_ns.route("/<username>/<coprname>/package/new/<source_type_text>", methods=["POST"])
@coprs_ns.route("/g/<group_name>/<coprname>/package/new/<source_type_text>", methods=["POST"])
@login_required
@req_with_copr
def copr_new_package(copr, source_type_text):
    url_on_success = helpers.copr_url("coprs_ns.copr_packages", copr)
    return process_save_package(copr, source_type_text, package_name=None, view="coprs_ns.copr_new_package",
                                view_method=copr_add_package, url_on_success=url_on_success)


@coprs_ns.route("/<username>/<coprname>/package/<package_name>/edit")
@coprs_ns.route("/<username>/<coprname>/package/<package_name>/edit/<source_type_text>")
@coprs_ns.route("/g/<group_name>/<coprname>/package/<package_name>/edit")
@coprs_ns.route("/g/<group_name>/<coprname>/package/<package_name>/edit/<source_type_text>")
@req_with_copr
def copr_edit_package(copr, package_name, source_type_text=None, **kwargs):
    package = ComplexLogic.get_package_safe(copr, package_name)
    data = package.source_json_dict
    data["webhook_rebuild"] = package.webhook_rebuild

    if package.has_source_type_set and not source_type_text:
        source_type_text = package.source_type_text
    elif not source_type_text:
        source_type_text = "scm"

    form_classes = {
        "scm": forms.PackageFormScm,
        "pypi": forms.PackageFormPyPI,
        "rubygems": forms.PackageFormRubyGems,
        "custom": forms.PackageFormCustom,
    }
    form = {k: v(formdata=None) for k, v in form_classes.items()}

    if "form" in kwargs:
        form[source_type_text] = kwargs["form"]
    elif package.has_source_type_set:
        form[package.source_type_text] = form_classes[package.source_type_text](data=data)

    return flask.render_template("coprs/detail/edit_package.html", package=package, copr=copr,
                                 source_type_text=source_type_text, view="coprs_ns.copr_edit_package",
                                 form_scm=form["scm"], form_pypi=form["pypi"],
                                 form_rubygems=form["rubygems"],
                                 form_custom=form['custom'])


@coprs_ns.route("/<username>/<coprname>/package/<package_name>/edit/<source_type_text>", methods=["POST"])
@coprs_ns.route("/g/<group_name>/<coprname>/package/<package_name>/edit/<source_type_text>", methods=["POST"])
@login_required
@req_with_copr
def copr_edit_package_post(copr, package_name, source_type_text):
    UsersLogic.raise_if_cant_build_in_copr(
        flask.g.user, copr, "You don't have permissions to edit this package.")

    url_on_success = helpers.copr_url("coprs_ns.copr_packages", copr)
    return process_save_package(copr, source_type_text, package_name, view="coprs_ns.copr_edit_package",
                                view_method=copr_edit_package, url_on_success=url_on_success)


def process_save_package(copr, source_type_text, package_name, view, view_method, url_on_success):
    form = forms.get_package_form_cls_by_source_type_text(source_type_text)()

    if "reset" in flask.request.form:
        try:
            package = PackagesLogic.get(copr.id, package_name)[0]
        except IndexError:
            flask.flash("Package {package_name} does not exist in copr {copr}.".format(package_name, copr.full_name))
            return flask.redirect(url_on_success) # should be url_on_fail

        try:
            PackagesLogic.reset_package(flask.g.user, package)
            db.session.commit()
        except InsufficientRightsException as e:
            flask.flash(str(e))
            return flask.redirect(url_on_success) # should be url_on_fail

        flask.flash("Package default source successfully reset.")
        return flask.redirect(url_on_success)

    if form.validate_on_submit():
        try:
            if package_name:
                package = PackagesLogic.get(copr.id, package_name)[0]
            else:
                package = PackagesLogic.add(flask.app.g.user, copr, form.package_name.data)

            package.source_type = helpers.BuildSourceEnum(source_type_text)
            package.webhook_rebuild = form.webhook_rebuild.data
            package.source_json = form.source_json

            db.session.add(package)
            db.session.commit()
        except (InsufficientRightsException, IndexError) as e:
            db.session.rollback()
            flask.flash(str(e), "error")
        else:
            flask.flash("Package successfully saved" if package_name else "New package has been created.")

        return flask.redirect(url_on_success)

    kwargs = {
        "coprname": copr.name,
        "package_name": package_name,
        "source_type_text": source_type_text,
        "form": form,
    }

    kwargs.update({"group_name": copr.group.name} if copr.is_a_group_project else {"username": copr.user.name})
    return view_method(**kwargs)


@coprs_ns.route("/<username>/<coprname>/package/<int:package_id>/delete", methods=["POST"])
@coprs_ns.route("/g/<group_name>/<coprname>/package/<int:package_id>/delete", methods=["POST"])
@login_required
@req_with_copr
def copr_delete_package(copr, package_id):
    package = ComplexLogic.get_package_by_id_safe(package_id)

    try:
        PackagesLogic.delete_package(flask.g.user, package)
    except (InsufficientRightsException, ActionInProgressException) as e:
        flask.flash(str(e), "error")
    else:
        db.session.commit()
        flask.flash("Package has been deleted successfully.", "success")

    return flask.redirect(helpers.copr_url("coprs_ns.copr_packages", copr))
