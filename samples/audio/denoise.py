# import soundfile as sf
# import noisereduce as nr

# def denoise_file(input_path, output_path):
#     """Pure audio work: read a file, reduce noise, write result.
#     Knows nothing about Django, Celery, or the database."""
#     audio, sample_rate = sf.read(input_path)
#     reduced = nr.reduce_noise(y=audio, sr=sample_rate)
#     sf.write(output_path, reduced, sample_rate)
#     return output_path