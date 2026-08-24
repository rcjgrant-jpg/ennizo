from django.shortcuts import render
from library.models import Sample
from django.shortcuts import get_object_or_404




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
    
def editor_home(request):
    return render(request, "processing/editor_home.html")    



    
