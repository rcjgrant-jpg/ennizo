from django.contrib import admin

from .models import Folder, Sample, SampleTag, Tag


class SampleTagInline(admin.TabularInline):
    model = SampleTag
    extra = 1


@admin.register(Sample)
class SampleAdmin(admin.ModelAdmin):
    list_display = ("title", "folder", "is_public", "created_at")
    list_filter = ("is_public", "folder__library__user")
    search_fields = ("title", "note")
    inlines = [SampleTagInline]


admin.site.register(Folder)
admin.site.register(Tag)
