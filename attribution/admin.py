from django.contrib import admin

from .models import CreditRecord, DownloadRecord


@admin.register(DownloadRecord)
class DownloadRecordAdmin(admin.ModelAdmin):
    list_display = ["downloader", "sample", "created_at"]
    list_select_related = ["downloader", "sample"]


@admin.register(CreditRecord)
class CreditRecordAdmin(admin.ModelAdmin):
    list_display = ["creditor", "sample", "platform", "track_title", "created_at"]
    list_select_related = ["creditor", "sample"]
