import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from library.models import Sample
from .tasks import render_sample




def _page_context(request, sample):
    """Everything both the full page and the polled fragment need."""

    return {
        "sample": sample,
        "metadata": getattr(sample, "metadata", None),
        "is_owner": sample.folder.library.user_id == request.user.id,
        "active_page": "edit_sample",
        "eq_bands": [63, 125, 250, 500, 1000, 2000, 4000, 8000],
    }

def edit_sample(request, pk):
    sample = get_object_or_404(
    Sample.objects.select_related("metadata"),
    pk=pk,
    folder__library__user=request.user,
    )
    
    return render(request, "processing/edit_sample.html", _page_context(request, sample))

@require_POST
def render_sample_view(request, pk):
    sample = get_object_or_404(
        Sample.objects.select_related("metadata"),
        pk=pk,
        folder__library__user=request.user,
    )

    try:
        params = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    trim_start = params.get("trim_start")
    trim_end = params.get("trim_end")
    if trim_start is not None and trim_end is not None:
        if not (isinstance(trim_start, (int, float))
                and isinstance(trim_end, (int, float))
                and trim_start >= 0
                and trim_end > trim_start):
            return JsonResponse({"error": "invalid trim"}, status=400)

    transaction.on_commit(lambda: render_sample.delay(sample.pk, params))
    return JsonResponse({"ok": True})
    
def editor_home(request):
    return render(request, "processing/editor_home.html")    



    
