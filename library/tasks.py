# samples/tasks.py
from celery import shared_task
from .models import Sample
# from .audio.denoise import denoise_file

@shared_task
def denoise_sample(sample_id):
    sample = Sample.objects.get(id=sample_id)

    input_path = sample.audio_file.path
    output_path = input_path.replace(".wav", "_clean.wav")

    # denoise_file(input_path, output_path)      # ← your actual audio work

    # save the cleaned file back onto the model, mark done
    with open(output_path, "rb") as f:
        sample.processed_file.save("clean.wav", f)
    sample.is_processed = True
    sample.save()