import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone

from library.models import Sample
from .tasks import render_sample



@require_GET
def render_status(request, pk):
    sample = get_object_or_404(
        Sample, pk=pk, folder__library__user=request.user
    )
    after = request.GET.get("after")
    renders = sample.renders.order_by("-pk")
    if after:
        renders = renders.filter(pk__gt=int(after))
    latest = renders.first()
    
    if latest:
        return JsonResponse(
            {"done": True, "render_pk": latest.pk, "url": latest.audio_file.url}
        )
        
    return JsonResponse({"done": False})

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
    Sample.objects.filter(pk=pk).update(last_active_at=timezone.now())
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
        
   
    gains = params.get("gains")
    if gains is not None:
        if not (isinstance(gains, list)
                and len(gains) == 8
                and all(isinstance(g, (int, float)) and -12 <= g <= 12 for g in gains)):
            return JsonResponse({"error": "invalid gains"}, status=400)
        
    for key in ("tame_peaks", "normalise", "preview"):
            if key in params and not isinstance(params[key], bool):
                return JsonResponse({"error": f"invalid {key}"}, status=400)

    transaction.on_commit(lambda: render_sample.delay(sample.pk, params))
    
    latest = sample.renders.order_by("-pk").first()
    return JsonResponse({"ok": True, "after": latest.pk if latest else 0})

    
    
def editor_home(request):
    return render(request, "processing/editor_home.html")    



    
