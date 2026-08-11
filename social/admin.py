from django.contrib import admin

from django.contrib import admin

from .models import Post, Comment, Like


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["author", "sample", "created_at"]
    list_filter = ["created_at"]


admin.site.register(Comment)
admin.site.register(Like)