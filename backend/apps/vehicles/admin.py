from django.contrib import admin, messages
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.db.models import Q

from apps.audit.admin_mixins import AuditedModelAdmin

from . import archiving
from .models import Brand, VehicleModel


class CascadingArchiveAdmin(AuditedModelAdmin):
    """Archive/un-archive actions and the edit form's is_active checkbox
    all cascade through apps.vehicles.archiving - same as the API."""

    archive = restore = archive_children = restore_children = None  # set per subclass

    def archive_one(self, request, instance):
        self._report(request, instance, type(self).archive(instance, actor=request.user, request=request))

    def unarchive_one(self, request, instance):
        self._report(request, instance, type(self).restore(instance, actor=request.user, request=request))

    def cascade_active_change(self, request, obj):
        cascade = type(self).restore_children if obj.is_active else type(self).archive_children
        self._report(request, obj, cascade(obj, actor=request.user, request=request))

    def _report(self, request, obj, plan):
        summary = plan.as_dict()
        changed = ", ".join(f"{count} {group.replace('_', ' ')}" for group, count in summary["counts"].items() if count)
        if changed:
            verb = "archived" if plan.action == "archive" else "reactivated"
            self.message_user(request, f"{obj}: also {verb} {changed}.", messages.SUCCESS)
        for skipped in summary["skipped"]:
            self.message_user(
                request,
                f"{obj}: {skipped['label']} (#{skipped['id']}) left archived - {skipped['reason']}.",
                messages.WARNING,
            )


@admin.register(Brand)
class BrandAdmin(CascadingArchiveAdmin, admin.ModelAdmin):
    list_display = ["name", "tier_code", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]

    archive = staticmethod(archiving.archive_brand)
    restore = staticmethod(archiving.restore_brand)
    archive_children = staticmethod(archiving.archive_brand_children)
    restore_children = staticmethod(archiving.restore_brand_children)

    def get_search_results(self, request, queryset, search_term):
        """QA audit M25: restricts the admin AUTOCOMPLETE endpoint's live
        search results (/admin/autocomplete/, used by VehicleModelAdmin's
        autocomplete_fields=["brand"]) to active brands only. Scoped to
        that endpoint specifically, not applied unconditionally - this is
        the SAME method Brand's own changelist search box calls, and an
        archived brand must stay findable/searchable there (that's how
        an admin finds one to un-archive it); filtering unconditionally
        here would also hide it from Brand's own list search, which M25
        never asked for.
        """
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        if request.path.endswith("/autocomplete/"):
            queryset = queryset.filter(is_active=True)
        return queryset, may_have_duplicates


@admin.register(VehicleModel)
class VehicleModelAdmin(CascadingArchiveAdmin, admin.ModelAdmin):
    archive = staticmethod(archiving.archive_vehicle)
    restore = staticmethod(archiving.restore_vehicle)
    archive_children = staticmethod(archiving.archive_vehicle_children)
    restore_children = staticmethod(archiving.restore_vehicle_children)

    list_display = [
        "brand", "name", "trim", "body_segment", "road_tax_class", "powertrain", "engine_capacity_cc", "msrp",
        "is_active",
    ]
    list_filter = ["brand", "body_segment", "road_tax_class", "powertrain", "is_active"]
    search_fields = ["name", "trim", "brand__name"]
    # H15: paired with the icon-stripping in formfield_for_foreignkey
    # below - BrandAdmin.search_fields (above) is what this requires on
    # the target model's own admin.
    autocomplete_fields = ["brand"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "brand":
            # QA audit M25: a staff user could otherwise create/re-point a
            # vehicle at an archived brand - the same category of bug H13
            # fixed for the public catalog, on the write side instead.
            # Exception: the vehicle's CURRENT brand stays selectable on
            # its own change form even if that brand has since been
            # archived - otherwise simply opening and re-saving an
            # existing vehicle's edit form unchanged would fail Django's
            # own ModelChoiceField validation ("that choice is not one of
            # the available choices"), a new 400 strictly worse than the
            # bug being fixed.
            #
            # object_id (present only on the change view's URL, absent on
            # add - there's no current value to protect there) is the
            # VEHICLE's own pk, NOT a brand pk - a first pass at this fix
            # used it directly as Q(pk=object_id) against Brand, which is
            # wrong (it would only coincidentally match a real brand) and
            # was caught by this fix's own test suite
            # (test_admin_brand_dropdown.py). The vehicle's current
            # brand_id has to be looked up via the vehicle itself.
            object_id = request.resolver_match.kwargs.get("object_id")
            current_brand_id = None
            if object_id:
                current_brand_id = (
                    VehicleModel.objects.filter(pk=object_id).values_list("brand_id", flat=True).first()
                )
            kwargs["queryset"] = (
                Brand.objects.filter(Q(is_active=True) | Q(pk=current_brand_id))
                if current_brand_id is not None
                else Brand.objects.filter(is_active=True)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # H15: NOT done inside formfield_for_foreignkey above - traced
        # against the real installed Django 5.2.17 source
        # (django.contrib.admin.options.ModelAdmin.formfield_for_dbfield):
        # the RelatedFieldWidgetWrapper that renders the "+"/pencil/
        # lookup icons is applied by THIS method, to whatever
        # formfield_for_foreignkey returns, AFTER that method already
        # returned - so unwrapping inside formfield_for_foreignkey itself
        # (as a first pass at this fix assumed) checks the widget before
        # it's ever wrapped, and the wrap gets silently reapplied right
        # after regardless. Overriding this method instead intercepts
        # AFTER the real wrap has happened.
        #
        # Those icons wire to Django's own bundled RelatedObjectLookups.js
        # ::showAdminPopup(), which calls window.open().focus() with no
        # null check - a popup blocker (the default for an unrecognized
        # site in most browsers) makes window.open() return null, and
        # that unchecked .focus() throws, silently: the popup never
        # opens, the brand field stays empty, and nothing on screen
        # explains why. The vendored JS ships with Django itself and must
        # not be patched directly (reverted on the next Django upgrade) -
        # unwrapping removes the icons (and therefore every path to that
        # crash) from this field only. BrandAdmin's own add/change pages
        # (/admin/vehicles/brand/add/) are untouched and remain the one
        # real way to add a brand.
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "brand" and isinstance(formfield.widget, RelatedFieldWidgetWrapper):
            formfield.widget = formfield.widget.widget
        return formfield
