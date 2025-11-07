Essentia models
This page provides a list of pre-trained models available in Essentia for various music and audio analysis tasks. To use Essentia with TensorFlow support refer to the guide on Using machine learning models. Click on the models below to access the weights (.pb) and metadata (.json) files, as well as example code snippets.

Additional legacy models are available in our model repository. Some models are also available in TensorFlow.js (tfjs.zip) and ONNX (.onnx) formats. As this is an ongoing project, we expect to keep adding new models and improved versions of the existing ones. These changes are tracked in this CHANGELOG.

All the models created by the MTG are licensed under CC BY-NC-SA 4.0 and are also available under proprietary license upon request. Check the LICENSE of the models.

Follow this link to see interactive demos of some of the models. Some of our models can work in real-time, opening many possibilities for audio developers. For example, see Python examples for MusiCNN-based music auto-tagging and classification of a live audio stream.

If you use any of the models in your research, please cite the following paper:

@inproceedings{alonso2020tensorflow,
  title={Tensorflow Audio Models in {Essentia}},
  author={Alonso-Jim{\'e}nez, Pablo and Bogdanov, Dmitry and Pons, Jordi and Serra, Xavier},
  booktitle={International Conference on Acoustics, Speech and Signal Processing ({ICASSP})},
  year={2020}
}
Feature extractors
AudioSet-VGGish
Audio embedding model accompanying the AudioSet dataset, trained in a supervised manner using tag information for YouTube videos.

Models:

⬇️ audioset-vggish

[weights, metadata]

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictVGGish

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = model(audio)
Discogs-EffNet
Audio embedding models trained with classification and contrastive learning objectives using an in-house dataset annotated with Discogs metadata. The classification model was trained to predict music style labels. The contrastive learning models were trained to learn music similarity capable of grouping audio tracks coming from the same artist, label (record label), release (album), or segments of the same track itself (self-supervised learning). Additionally, multi was trained in multiple similarity targets simultaneously.

Models:

⬇️ discogs-effnet-bs64

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = model(audio)
⬇️ discogs_artist_embeddings-effnet-bs64

[weights, metadata]

Model trained with a contrastive learning objective targeting artist associations.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_artist_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = model(audio)
⬇️ discogs_label_embeddings-effnet-bs64

[weights, metadata]

Model trained with a contrastive learning objective targeting record label associations.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_label_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = model(audio)
⬇️ discogs_multi_embeddings-effnet-bs64

[weights, metadata]

Model trained with a contrastive learning objective targeting aritst and track associations in a multi-task setup.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_multi_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = model(audio)
⬇️ discogs_release_embeddings-effnet-bs64

[weights, metadata]

Model trained with a contrastive learning objective targeting release (album) associations.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_release_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = model(audio)
⬇️ discogs_track_embeddings-effnet-bs64

[weights, metadata]

Model trained with a contrastive learning objective targeting track (self-supervised) associations.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_track_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = model(audio)
Note: We provide models operating with a fixed batch size of 64 samples since it was not possible to port the version with dynamic batch size from ONNX to TensorFlow. Additionally, an ONNX version of the model with dynamic batch size is provided.

MAEST
Music Audio Efficient Spectrogram Transformer (MAEST) trained to predict music style labels using an in-house dataset annotated with Discogs metadata. We offer versions of MAEST trained with sequence lengths ranging from 5 to 30 seconds (5s, 10s, 20s, and 30s), and trained starting from different intial weights: from random initialization (fs), from DeiT pre-trained weights (dw), and from PaSST pre-trained weights (pw). Additionally, we offer a version of MAEST trained following a teacher student setup (ts). According to our study discogs-maest-30s-pw, achieved the most competitive performance in most downstream tasks (refer to the paper for details).

The output embeddings have shape [batch_size, 1, tokens, embedding_size], where the first and second tokens (i.e., [0, 0, :2, :] ) correspond to the CLS and DIST tokens respectively, and the following ones to input signal. To train downstream models, we recommend using the embeddings from the CLS token, or stacking the CLS, DIST, and the average of the input signal tokens for slightly better performance (refer to the paper for details).

In the following examples, we extract embeddings from the 7th layer of the transformer since this is what performed the best in our downstream classification tasks. To extract embeddings from other layers, change the output parameter according to the layer names provided in the metadata files.

Models:

⬇️ discogs-maest-30s-pw-519l

[weights, metadata]

Model trained with a multi-label classification objective targeting 519 Discogs styles on an extended dataset of 4M tracks.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-30s-pw-519l-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-30s-pw

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-30s-pw-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-30s-pw-ts

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-30s-pw-ts-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-20s-pw

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-20s-pw-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-10s-pw

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-10s-pw-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-10s-fs

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-10s-fs-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-10s-dw

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-10s-dw-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
⬇️ discogs-maest-5s-pw

[weights, metadata]

Model trained with a multi-label classification objective targeting 400 Discogs styles.

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMAEST

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMAEST(graphFilename="discogs-maest-5s-pw-2.pb", output="PartitionedCall/Identity_7")
embeddings = model(audio)
Note: discogs-maest-30s-pw-519l is an updated version of MAEST trained on a larger dataset of 4M tracks and 519 music style lables. It is expected to show slightly better performance.

Note: We provide TensorFlow models operating with a fixed batch size of 1. Additionally, ONNX version of the models supporting dynamic batch sizes are provided.

OpenL3
Audio embedding models trained on audio-visual correspondence in a self-supervised manner. There are different versions of OpenL3 trained on environmental sound (env) or music (music) datasets, using 128 (mel128) or 256 (mel256) mel-bands, and with 512 (emb512) or 6144 (emb6144) embedding dimensions.

Models:

⬇️ openl3-env-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-env-mel128-emb6144

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-env-mel256-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-env-mel256-emb6144

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-music-mel128-emb6144

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-music-mel256-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

⬇️ openl3-music-mel256-emb6144

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

MSD-MusiCNN
A Music embedding extractor based on auto-tagging with the 50 most common tags of the Million Song Dataset.

Models:

⬇️ msd-musicnn

[weights, metadata]

Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = model(audio)
Classifiers
Classification and regression models based on embeddings. Instead of working with mel-spectrograms, these models require embeddings as input. The name of these models is a combination of the classification/regression task and the name of the embedding model that should be used to extract embeddings (<classification_task>-<embedding_model>).

Note: TensorflowPredict2D has to be configured with the correct output layer name for each classifier. Check the attached JSON file to find the name of the output layer on each case.

Music genre and style
Genre Discogs400
Music style classification by 400 styles from the Discogs taxonomy:

Blues: Boogie Woogie, Chicago Blues, Country Blues, Delta Blues, Electric Blues, Harmonica Blues, Jump Blues, Louisiana Blues, Modern Electric Blues, Piano Blues, Rhythm & Blues, Texas Blues
Brass & Military: Brass Band, Marches, Military
Children's: Educational, Nursery Rhymes, Story
Classical: Baroque, Choral, Classical, Contemporary, Impressionist, Medieval, Modern, Neo-Classical, Neo-Romantic, Opera, Post-Modern, Renaissance, Romantic
Electronic: Abstract, Acid, Acid House, Acid Jazz, Ambient, Bassline, Beatdown, Berlin-School, Big Beat, Bleep, Breakbeat, Breakcore, Breaks, Broken Beat, Chillwave, Chiptune, Dance-pop, Dark Ambient, Darkwave, Deep House, Deep Techno, Disco, Disco Polo, Donk, Downtempo, Drone, Drum n Bass, Dub, Dub Techno, Dubstep, Dungeon Synth, EBM, Electro, Electro House, Electroclash, Euro House, Euro-Disco, Eurobeat, Eurodance, Experimental, Freestyle, Future Jazz, Gabber, Garage House, Ghetto, Ghetto House, Glitch, Goa Trance, Grime, Halftime, Hands Up, Happy Hardcore, Hard House, Hard Techno, Hard Trance, Hardcore, Hardstyle, Hi NRG, Hip Hop, Hip-House, House, IDM, Illbient, Industrial, Italo House, Italo-Disco, Italodance, Jazzdance, Juke, Jumpstyle, Jungle, Latin, Leftfield, Makina, Minimal, Minimal Techno, Modern Classical, Musique Concrète, Neofolk, New Age, New Beat, New Wave, Noise, Nu-Disco, Power Electronics, Progressive Breaks, Progressive House, Progressive Trance, Psy-Trance, Rhythmic Noise, Schranz, Sound Collage, Speed Garage, Speedcore, Synth-pop, Synthwave, Tech House, Tech Trance, Techno, Trance, Tribal, Tribal House, Trip Hop, Tropical House, UK Garage, Vaporwave
Folk, World, & Country: African, Bluegrass, Cajun, Canzone Napoletana, Catalan Music, Celtic, Country, Fado, Flamenco, Folk, Gospel, Highlife, Hillbilly, Hindustani, Honky Tonk, Indian Classical, Laïkó, Nordic, Pacific, Polka, Raï, Romani, Soukous, Séga, Volksmusik, Zouk, Éntekhno
Funk / Soul: Afrobeat, Boogie, Contemporary R&B, Disco, Free Funk, Funk, Gospel, Neo Soul, New Jack Swing, P.Funk, Psychedelic, Rhythm & Blues, Soul, Swingbeat, UK Street Soul
Hip Hop: Bass Music, Boom Bap, Bounce, Britcore, Cloud Rap, Conscious, Crunk, Cut-up/DJ, DJ Battle Tool, Electro, G-Funk, Gangsta, Grime, Hardcore Hip-Hop, Horrorcore, Instrumental, Jazzy Hip-Hop, Miami Bass, Pop Rap, Ragga HipHop, RnB/Swing, Screw, Thug Rap, Trap, Trip Hop, Turntablism
Jazz: Afro-Cuban Jazz, Afrobeat, Avant-garde Jazz, Big Band, Bop, Bossa Nova, Contemporary Jazz, Cool Jazz, Dixieland, Easy Listening, Free Improvisation, Free Jazz, Fusion, Gypsy Jazz, Hard Bop, Jazz-Funk, Jazz-Rock, Latin Jazz, Modal, Post Bop, Ragtime, Smooth Jazz, Soul-Jazz, Space-Age, Swing
Latin: Afro-Cuban, Baião, Batucada, Beguine, Bolero, Boogaloo, Bossanova, Cha-Cha, Charanga, Compas, Cubano, Cumbia, Descarga, Forró, Guaguancó, Guajira, Guaracha, MPB, Mambo, Mariachi, Merengue, Norteño, Nueva Cancion, Pachanga, Porro, Ranchera, Reggaeton, Rumba, Salsa, Samba, Son, Son Montuno, Tango, Tejano, Vallenato
Non-Music: Audiobook, Comedy, Dialogue, Education, Field Recording, Interview, Monolog, Poetry, Political, Promotional, Radioplay, Religious, Spoken Word
Pop: Ballad, Bollywood, Bubblegum, Chanson, City Pop, Europop, Indie Pop, J-pop, K-pop, Kayōkyoku, Light Music, Music Hall, Novelty, Parody, Schlager, Vocal
Reggae: Calypso, Dancehall, Dub, Lovers Rock, Ragga, Reggae, Reggae-Pop, Rocksteady, Roots Reggae, Ska, Soca
Rock: AOR, Acid Rock, Acoustic, Alternative Rock, Arena Rock, Art Rock, Atmospheric Black Metal, Avantgarde, Beat, Black Metal, Blues Rock, Brit Pop, Classic Rock, Coldwave, Country Rock, Crust, Death Metal, Deathcore, Deathrock, Depressive Black Metal, Doo Wop, Doom Metal, Dream Pop, Emo, Ethereal, Experimental, Folk Metal, Folk Rock, Funeral Doom Metal, Funk Metal, Garage Rock, Glam, Goregrind, Goth Rock, Gothic Metal, Grindcore, Grunge, Hard Rock, Hardcore, Heavy Metal, Indie Rock, Industrial, Krautrock, Lo-Fi, Lounge, Math Rock, Melodic Death Metal, Melodic Hardcore, Metalcore, Mod, Neofolk, New Wave, No Wave, Noise, Noisecore, Nu Metal, Oi, Parody, Pop Punk, Pop Rock, Pornogrind, Post Rock, Post-Hardcore, Post-Metal, Post-Punk, Power Metal, Power Pop, Power Violence, Prog Rock, Progressive Metal, Psychedelic Rock, Psychobilly, Pub Rock, Punk, Rock & Roll, Rockabilly, Shoegaze, Ska, Sludge Metal, Soft Rock, Southern Rock, Space Rock, Speed Metal, Stoner Rock, Surf, Symphonic Rock, Technical Death Metal, Thrash, Twist, Viking Metal, Yé-Yé
Stage & Screen: Musical, Score, Soundtrack, Theme
Models:

⬇️ genre_discogs400-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="genre_discogs400-discogs-effnet-1.pb", input="serving_default_model_Placeholder", output="PartitionedCall:0")
predictions = model(embeddings)
⬇️ genre_discogs400-discogs-maest-5s-pw

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-5s-pw-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-5s-pw-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
⬇️ genre_discogs400-discogs-maest-10-pw

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-10s-pw-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-10s-pw-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
⬇️ genre_discogs400-discogs-maest-10s-fs

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-10s-fs-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-10s-fs-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
⬇️ genre_discogs400-discogs-maest-30s-dw

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-10s-dw-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-10s-dw-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
⬇️ genre_discogs400-discogs-maest-20s-pw

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-20s-pw-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-20s-pw-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
⬇️ genre_discogs400-discogs-maest-30s-pw

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-30s-pw-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-30s-pw-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
⬇️ genre_discogs400-discogs-maest-30s-pw-ts

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-30s-pw-ts-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs400-discogs-maest-30s-pw-ts-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
Genre Discogs519
Music style classification by 519 styles from the Discogs taxonomy:

Blues: Boogie Woogie, Chicago Blues, Country Blues, Delta Blues, East Coast Blues, Electric Blues, Harmonica Blues, Jump Blues, Louisiana Blues, Memphis Blues, Modern Electric Blues, Piano Blues, Piedmont Blues, Rhythm & Blues, Texas Blues
Brass & Military: Brass Band, Marches, Military, Pipe & Drum
Children's: Educational, Nursery Rhymes, Story
Classical: Baroque, Choral, Classical, Contemporary, Early, Impressionist, Medieval, Modern, Neo-Classical, Neo-Romantic, Opera, Operetta, Oratorio, Post-Modern, Renaissance, Romantic, Twelve-tone
Electronic: Abstract, Acid, Acid House, Acid Jazz, Ambient, Baltimore Club, Bassline, Beatdown, Berlin-School, Big Beat, Bleep, Breakbeat, Breakcore, Breaks, Broken Beat, Chillwave, Chiptune, Dance-pop, Dark Ambient, Darkwave, Deep House, Deep Techno, Disco, Disco Polo, Donk, Doomcore, Downtempo, Drone, Drum n Bass, Dub, Dub Techno, Dubstep, Dungeon Synth, EBM, Electro, Electro House, Electroacoustic, Electroclash, Euro House, Euro-Disco, Eurobeat, Eurodance, Experimental, Footwork, Freestyle, Future Jazz, Gabber, Garage House, Ghetto, Ghetto House, Ghettotech, Glitch, Glitch Hop, Goa Trance, Grime, Halftime, Hands Up, Happy Hardcore, Hard Beat, Hard House, Hard Techno, Hard Trance, Hardcore, Hardstyle, Harsh Noise Wall, Hi NRG, Hip Hop, Hip-House, House, IDM, Illbient, Industrial, Italo House, Italo-Disco, Italodance, J-Core, Jazzdance, Juke, Jumpstyle, Jungle, Latin, Leftfield, Lento Violento, Makina, Minimal, Minimal Techno, Modern Classical, Musique Concrète, Neo Trance, Neofolk, New Age, New Beat, New Wave, Noise, Nu-Disco, Power Electronics, Progressive Breaks, Progressive House, Progressive Trance, Psy-Trance, Rhythmic Noise, Schranz, Sound Collage, Speed Garage, Speedcore, Synth-pop, Synthwave, Tech House, Tech Trance, Techno, Trance, Tribal, Tribal House, Trip Hop, Tropical House, UK Funky, UK Garage, Vaporwave, Witch House
Folk, World, & Country: Aboriginal, African, Andalusian Classical, Andean Music, Appalachian Music, Basque Music, Bhangra, Bluegrass, Cajun, Canzone Napoletana, Carnatic, Catalan Music, Celtic, Chacarera, Chinese Classical, Chutney, Copla, Country, Cretan, Dangdut, Fado, Flamenco, Folk, Funaná, Gamelan, Ghazal, Gospel, Griot, Hawaiian, Highlife, Hillbilly, Hindustani, Honky Tonk, Indian Classical, Kaseko, Klezmer, Laïkó, Luk Thung, Maloya, Mbalax, Min'yō, Mizrahi, Nhạc Vàng, Nordic, Népzene, Ottoman Classical, Overtone Singing, Pacific, Pasodoble, Persian Classical, Phleng Phuea Chiwit, Polka, Qawwali, Raï, Rebetiko, Romani, Salegy, Sea Shanties, Soukous, Séga, Volksmusik, Western Swing, Zouk, Zydeco, Éntekhno
Funk / Soul: Afrobeat, Bayou Funk, Boogie, Contemporary R&B, Disco, Free Funk, Funk, Gogo, Gospel, Minneapolis Sound, Neo Soul, New Jack Swing, P.Funk, Psychedelic, Rhythm & Blues, Soul, Swingbeat, UK Street Soul
Hip Hop: Bass Music, Beatbox, Boom Bap, Bounce, Britcore, Cloud Rap, Conscious, Crunk, Cut-up/DJ, DJ Battle Tool, Electro, Favela Funk, G-Funk, Gangsta, Go-Go, Grime, Hardcore Hip-Hop, Hiplife, Horrorcore, Hyphy, Instrumental, Jazzy Hip-Hop, Kwaito, Miami Bass, Pop Rap, Ragga HipHop, RnB/Swing, Screw, Thug Rap, Trap, Trip Hop, Turntablism
Jazz: Afro-Cuban Jazz, Afrobeat, Avant-garde Jazz, Big Band, Bop, Bossa Nova, Cape Jazz, Contemporary Jazz, Cool Jazz, Dixieland, Easy Listening, Free Improvisation, Free Jazz, Fusion, Gypsy Jazz, Hard Bop, Jazz-Funk, Jazz-Rock, Latin Jazz, Modal, Post Bop, Ragtime, Smooth Jazz, Soul-Jazz, Space-Age, Swing
Latin: Afro-Cuban, Axé, Bachata, Baião, Batucada, Beguine, Bolero, Boogaloo, Bossanova, Carimbó, Cha-Cha, Charanga, Choro, Compas, Conjunto, Corrido, Cubano, Cumbia, Danzon, Descarga, Forró, Gaita, Guaguancó, Guajira, Guaracha, Jibaro, Lambada, MPB, Mambo, Mariachi, Marimba, Merengue, Música Criolla, Norteño, Nueva Cancion, Nueva Trova, Pachanga, Plena, Porro, Quechua, Ranchera, Reggaeton, Rumba, Salsa, Samba, Samba-Canção, Son, Son Montuno, Sonero, Tango, Tejano, Timba, Trova, Vallenato
Non-Music: Audiobook, Comedy, Dialogue, Education, Erotic, Field Recording, Health-Fitness, Interview, Monolog, Movie Effects, Poetry, Political, Promotional, Public Broadcast, Radioplay, Religious, Sermon, Sound Art, Sound Poetry, Special Effects, Speech, Spoken Word, Technical, Therapy
Pop: Ballad, Barbershop, Bollywood, Break-In, Bubblegum, Chanson, City Pop, Enka, Ethno-pop, Europop, Indie Pop, J-pop, K-pop, Karaoke, Kayōkyoku, Levenslied, Light Music, Music Hall, Novelty, Parody, Schlager, Vocal
Reggae: Calypso, Dancehall, Dub, Dub Poetry, Lovers Rock, Mento, Ragga, Reggae, Reggae Gospel, Reggae-Pop, Rocksteady, Roots Reggae, Ska, Soca, Steel Band
Rock: AOR, Acid Rock, Acoustic, Alternative Rock, Arena Rock, Art Rock, Atmospheric Black Metal, Avantgarde, Beat, Black Metal, Blues Rock, Brit Pop, Classic Rock, Coldwave, Country Rock, Crust, Death Metal, Deathcore, Deathrock, Depressive Black Metal, Doo Wop, Doom Metal, Dream Pop, Emo, Ethereal, Experimental, Folk Metal, Folk Rock, Funeral Doom Metal, Funk Metal, Garage Rock, Glam, Goregrind, Goth Rock, Gothic Metal, Grindcore, Groove Metal, Grunge, Hard Rock, Hardcore, Heavy Metal, Horror Rock, Indie Rock, Industrial, Industrial Metal, J-Rock, Jangle Pop, K-Rock, Krautrock, Lo-Fi, Lounge, Math Rock, Melodic Death Metal, Melodic Hardcore, Metalcore, Mod, NDW, Neofolk, New Wave, No Wave, Noise, Noisecore, Nu Metal, Oi, Parody, Pop Punk, Pop Rock, Pornogrind, Post Rock, Post-Hardcore, Post-Metal, Post-Punk, Power Metal, Power Pop, Power Violence, Prog Rock, Progressive Metal, Psychedelic Rock, Psychobilly, Pub Rock, Punk, Rock & Roll, Rock Opera, Rockabilly, Shoegaze, Ska, Skiffle, Sludge Metal, Soft Rock, Southern Rock, Space Rock, Speed Metal, Stoner Rock, Surf, Swamp Pop, Symphonic Rock, Technical Death Metal, Thrash, Twist, Viking Metal, Yé-Yé
Stage & Screen: Musical, Score, Soundtrack, Theme
Models:

⬇️ genre_discogs519

[weights, metadata, demo]

python code for predictions:

from essentia import Pool
from essentia.standard import MonoLoader, TensorflowPredictMAEST, TensorflowPredict

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMAEST(graphFilename="discogs-maest-30s-pw-519l-2.pb", output="PartitionedCall/Identity_12")
embeddings = embedding_model(audio)

pool = Pool()
pool.set("embeddings", embeddings)

model = TensorflowPredict(graphFilename="genre_discogs519-discogs-maest-30s-pw-519l-1.pb", inputs=["embeddings"], outputs=["PartitionedCall/Identity_1"])
predictions = model(pool)["PartitionedCall/Identity_1"]
MTG-Jamendo genre
Multi-label classification with the genre subset of MTG-Jamendo Dataset (87 classes):

60s, 70s, 80s, 90s, acidjazz, alternative, alternativerock, ambient, atmospheric, blues, bluesrock, bossanova, breakbeat,
celtic, chanson, chillout, choir, classical, classicrock, club, contemporary, country, dance, darkambient, darkwave,
deephouse, disco, downtempo, drumnbass, dub, dubstep, easylistening, edm, electronic, electronica, electropop, ethno,
eurodance, experimental, folk, funk, fusion, groove, grunge, hard, hardrock, hiphop, house, idm, improvisation, indie,
industrial, instrumentalpop, instrumentalrock, jazz, jazzfusion, latin, lounge, medieval, metal, minimal, newage, newwave,
orchestral, pop, popfolk, poprock, postrock, progressive, psychedelic, punkrock, rap, reggae, rnb, rock, rocknroll,
singersongwriter, soul, soundtrack, swing, symphonic, synthpop, techno, trance, triphop, world, worldfusion
Models:

⬇️ mtg_jamendo_genre-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_genre-discogs-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_genre-discogs_artist_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_artist_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_genre-discogs_artist_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_genre-discogs_label_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_label_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_genre-discogs_label_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_genre-discogs_multi_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_multi_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_genre-discogs_multi_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_genre-discogs_release_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_release_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_genre-discogs_release_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_genre-discogs_track_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_track_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_genre-discogs_track_embeddings-effnet-1.pb")
predictions = model(embeddings)
Moods and context
Approachability
Music approachability predicts whether the music is likely to be accessible to the general public (e.g., belonging to common mainstream music genres vs. niche and experimental genres). The models output rather two (approachability_2c) or three (approachability_3c) levels of approachability or continous values (approachability_regression).

Models:

⬇️ approachability_2c-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="approachability_2c-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ approachability_3c-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="approachability_3c-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ approachability_regression-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="approachability_regression-discogs-effnet-1.pb", output="model/Identity")
predictions = model(embeddings)
Engagement
Music engagement predicts whether the music evokes active attention of the listener (high-engagement “lean forward” active listening vs. low-engagement “lean back” background listening). The models output rather two (engagement_2c) or three (engagement_3c) levels of engagement or continuous (engagement_regression) values (regression).

Models:

⬇️ engagement_2c-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="engagement_2c-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ engagement_3c-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="engagement_3c-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ engagement_regression-discogs-effnet

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="engagement_regression-discogs-effnet-1.pb", output="model/Identity")
predictions = model(embeddings)
Arousal/valence DEAM
Music arousal and valence regression with the DEAM dataset (2 dimensions, range [1, 9]):

valence, arousal
Models:

⬇️ deam-msd-musicnn

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="deam-msd-musicnn-2.pb", output="model/Identity")
predictions = model(embeddings)
⬇️ deam-audioset-vggish

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="deam-audioset-vggish-2.pb", output="model/Identity")
predictions = model(embeddings)
Arousal/valence emoMusic
Music arousal and valence regression with the emoMusic dataset (2 dimensions, range [1, 9]):

valence, arousal
Models:

⬇️ emomusic-msd-musicnn

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="emomusic-msd-musicnn-2.pb", output="model/Identity")
predictions = model(embeddings)
⬇️ emomusic-audioset-vggish

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="emomusic-audioset-vggish-2.pb", output="model/Identity")
predictions = model(embeddings)
Arousal/valence MuSe
Music arousal and valence regression with the MuSE dataset (2 dimensions, range [1, 9]):

valence, arousal
Models:

⬇️ muse-msd-musicnn

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="muse-msd-musicnn-2.pb", output="model/Identity")
predictions = model(embeddings)
⬇️ muse-audioset-vggish

[weights, metadata, demo]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="muse-audioset-vggish-2.pb", output="model/Identity")
predictions = model(embeddings)
Danceability
Music danceability (2 classes):

danceable, not_danceable
Models:

⬇️ danceability-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="danceability-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ danceability-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="danceability-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ danceability-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="danceability-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ danceability-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="danceability-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ danceability-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Mood Aggressive
Music classification by mood (2 classes):

aggressive, non_aggressive
Models:

⬇️ mood_aggressive-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_aggressive-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_aggressive-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_aggressive-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_aggressive-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_aggressive-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_aggressive-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_aggressive-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_aggressive-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Mood Happy
Music classification by mood (2 classes):

happy, non_happy
Models:

⬇️ mood_happy-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_happy-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_happy-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_happy-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_happy-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_happy-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_happy-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_happy-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_happy-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Mood Party
Music classification by mood (2 classes):

party, non_party
Models:

⬇️ mood_party-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_party-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_party-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_party-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_party-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_party-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_party-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_party-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_party-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Mood Relaxed
Music classification by mood (2 classes):

relaxed, non_relaxed
Models:

⬇️ mood_relaxed-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_relaxed-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_relaxed-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_relaxed-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_relaxed-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_relaxed-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_relaxed-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_relaxed-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_relaxed-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Mood Sad
Music classification by mood (2 classes):

sad, non_sad
Models:

⬇️ mood_sad-audioset-yvggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_sad-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_sad-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_sad-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_sad-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_sad-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_sad-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_sad-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_sad-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Moods MIREX
Music classification by mood with the MIREX Audio Mood Classification Dataset (5 mood clusters):

1. passionate, rousing, confident, boisterous, rowdy
2. rollicking, cheerful, fun, sweet, amiable/good natured
3. literate, poignant, wistful, bittersweet, autumnal, brooding
4. humorous, silly, campy, quirky, whimsical, witty, wry
5. aggressive, fiery, tense/anxious, intense, volatile, visceral
Models:

⬇️ moods_mirex-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="moods_mirex-msd-musicnn-1.pb", input="serving_default_model_Placeholder", output="PartitionedCall")
predictions = model(embeddings)
⬇️ moods_mirex-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="moods_mirex-audioset-vggish-1.pb", input="serving_default_model_Placeholder", output="PartitionedCall")
predictions = model(embeddings)
MTG-Jamendo mood and theme
Multi-label classification with mood and theme subset of the MTG-Jamendo Dataset (56 classes):

action, adventure, advertising, background, ballad, calm, children, christmas, commercial, cool, corporate, dark, deep,
documentary, drama, dramatic, dream, emotional, energetic, epic, fast, film, fun, funny, game, groovy, happy, heavy,
holiday, hopeful, inspiring, love, meditative, melancholic, melodic, motivational, movie, nature, party, positive,
powerful, relaxing, retro, romantic, sad, sexy, slow, soft, soundscape, space, sport, summer, trailer, travel, upbeat,
uplifting
Models:

⬇️ mtg_jamendo_moodtheme-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_moodtheme-discogs-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_moodtheme-discogs_artist_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_artist_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_moodtheme-discogs_artist_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_moodtheme-discogs_label_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_label_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_moodtheme-discogs_label_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_moodtheme-discogs_multi_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_multi_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_moodtheme-discogs_multi_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_moodtheme-discogs_release_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_release_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_moodtheme-discogs_release_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_moodtheme-discogs_track_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_track_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_moodtheme-discogs_track_embeddings-effnet-1.pb")
predictions = model(embeddings)
Instrumentation
MTG-Jamendo instrument
Multi-label classification using the instrument subset of the MTG-Jamendo Dataset (40 classes):

accordion, acousticbassguitar, acousticguitar, bass, beat, bell, bongo, brass, cello, clarinet, classicalguitar, computer,
doublebass, drummachine, drums, electricguitar, electricpiano, flute, guitar, harmonica, harp, horn, keyboard, oboe,
orchestra, organ, pad, percussion, piano, pipeorgan, rhodes, sampler, saxophone, strings, synthesizer, trombone, trumpet,
viola, violin, voice
Models:

⬇️ mtg_jamendo_instrument-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_instrument-discogs-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_instrument-discogs_artist_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_artist_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_instrument-discogs_artist_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_instrument-discogs_label_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_label_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_instrument-discogs_label_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_instrument-discogs_multi_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_multi_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_instrument-discogs_multi_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_instrument-discogs_release_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_release_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_instrument-discogs_release_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_instrument-discogs_track_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_track_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_instrument-discogs_track_embeddings-effnet-1.pb")
predictions = model(embeddings)
Music loop instrument role
Classification of music loops by their instrument role using the Freesound Loop Dataset (5 classes):

bass, chords, fx, melody, percussion
Models:

⬇️ fs_loop_ds-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="fs_loop_ds-msd-musicnn-1.pb", input="serving_default_model_Placeholder", output="PartitionedCall")
predictions = model(embeddings)
Mood Acoustic
Music classification by type of sound (2 classes):

acoustic, non_acoustic
Models:

⬇️ mood_acoustic-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_acoustic-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_acoustic-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_acoustic-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_acoustic-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_acoustic-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_acoustic-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_acoustic-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_acoustic-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Mood Electronic
Music classification by type of sound (2 classes):

electronic, non_electronic
Models:

⬇️ mood_electronic-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_electronic-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_electronic-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_electronic-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_electronic-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_electronic-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_electronic-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mood_electronic-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ mood_electronic-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Voice/instrumental
Classification of music by presence or absence of voice (2 classes):

instrumental, voice
Models:

⬇️ voice_instrumental-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="voice_instrumental-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ voice_instrumental-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="voice_instrumental-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ voice_instrumental-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="voice_instrumental-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ voice_instrumental-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="voice_instrumental-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ voice_instrumental-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Voice gender
Classification of music by singing voice gender (2 classes):

female, male
Models:

⬇️ gender-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="gender-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ gender-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="gender-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ gender-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="gender-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ gender-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="gender-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ gender-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Timbre
Classification of music by timbre color (2 classes):

bright, dark
Models:

⬇️ timbre-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="timbre-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
Nsynth acoustic/electronic
Classification of monophonic sources into acoustic or electronic origin using the Nsynth dataset (2 classes):

acoustic, electronic
Models:

⬇️ nsynth_acoustic_electronic-discogs-effnet
Nsynth bright/dark
Classification of monophonic sources by timbre color using the Nsynth dataset (2 classes):

bright, dark
Models:

⬇️ nsynth_bright_dark-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="nsynth_bright_dark-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
Nsynth instrument
Classification of monophonic sources by instrument family using the Nsynth dataset (11 classes):

mallet, string, reed, guitar, synth_lead, vocal, bass, flute, keyboard, brass, organ
Models:

⬇️ nsynth_instrument-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="nsynth_instrument-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
Nsynth reverb
Detection of reverb in monophonic sources using the Nsynth dataset (2 classes):

dry, wet
Models:

⬇️ nsynth_reverb-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="nsynth_reverb-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
Tonality
Tonal/atonal
Music classification by tonality (2 classes):

atonal, tonal
Models:

⬇️ tonal_atonal-audioset-vggish

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-vggish-3.pb", output="model/vggish/embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="tonal_atonal-audioset-vggish-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ tonal_atonal-audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="tonal_atonal-audioset-yamnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ tonal_atonal-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="tonal_atonal-discogs-effnet-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ tonal_atonal-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="tonal_atonal-msd-musicnn-1.pb", output="model/Softmax")
predictions = model(embeddings)
⬇️ tonal_atonal-openl3-music-mel128-emb512

[weights, metadata]

We do not have a dedicated algorithm to extract embeddings with this model. For now, OpenL3 embeddings can be extracted using this script.

Miscellaneous tags
MTG-Jamendo top50tags
Music automatic tagging using the top-50 tags of the MTG-Jamendo Dataset:

alternative, ambient, atmospheric, chillout, classical, dance, downtempo, easylistening, electronic, experimental, folk,
funk, hiphop, house, indie, instrumentalpop, jazz, lounge, metal, newage, orchestral, pop, popfolk, poprock, reggae, rock,
soundtrack, techno, trance, triphop, world, acousticguitar, bass, computer, drummachine, drums, electricguitar,
electricpiano, guitar, keyboard, piano, strings, synthesizer, violin, voice, emotional, energetic, film, happy, relaxing
Models:

⬇️ mtg_jamendo_top50tags-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_top50tags-discogs-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_top50tags-discogs_label_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_label_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_top50tags-discogs_label_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_top50tags-discogs_multi_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_multi_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_top50tags-discogs_multi_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_top50tags-discogs_release_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_release_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_top50tags-discogs_release_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtg_jamendo_top50tags-discogs_track_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_track_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtg_jamendo_top50tags-discogs_track_embeddings-effnet-1.pb")
predictions = model(embeddings)
MagnaTagATune
Music automatic tagging with the top-50 tags of the MagnaTagATune dataset:

ambient, beat, beats, cello, choir, choral, classic, classical, country, dance, drums, electronic, fast, female, female
vocal, female voice, flute, guitar, harp, harpsichord, indian, loud, male, male vocal, male voice, man, metal, new age, no
vocal, no vocals, no voice, opera, piano, pop, quiet, rock, singing, sitar, slow, soft, solo, strings, synth, techno,
violin, vocal, vocals, voice, weird, woman
Models:

⬇️ mtt-discogs-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtt-discogs-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtt-discogs_artist_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_artist_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtt-discogs_artist_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtt-discogs_label_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_label_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtt-discogs_label_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtt-discogs_multi_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_multi_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtt-discogs_multi_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtt-discogs_release_embeddings-effnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_release_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtt-discogs_release_embeddings-effnet-1.pb")
predictions = model(embeddings)
⬇️ mtt-discogs_track_embeddings-effnet

[weights, metadata]

from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictEffnetDiscogs(graphFilename="discogs_track_embeddings-effnet-bs64-1.pb", output="PartitionedCall:1")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="mtt-discogs_track_embeddings-effnet-1.pb")
predictions = model(embeddings)
Million Song Dataset
Music automatic tagging using the top-50 tags of the LastFM/Million Song Dataset:

rock, pop, alternative, indie, electronic, female vocalists, dance, 00s, alternative rock, jazz, beautiful, metal,
chillout, male vocalists, classic rock, soul, indie rock, Mellow, electronica, 80s, folk, 90s, chill, instrumental, punk,
oldies, blues, hard rock, ambient, acoustic, experimental, female vocalist, guitar, Hip-Hop, 70s, party, country, easy
listening, sexy, catchy, funk, electro, heavy metal, Progressive rock, 60s, rnb, indie pop, sad, House, happy
Models:

⬇️ msd-msd-musicnn

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictMusiCNN, TensorflowPredict2D

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
embedding_model = TensorflowPredictMusiCNN(graphFilename="msd-musicnn-1.pb", output="model/dense/BiasAdd")
embeddings = embedding_model(audio)

model = TensorflowPredict2D(graphFilename="msd-msd-musicnn-1.pb", input="serving_default_model_Placeholder", output="PartitionedCall")
predictions = model(embeddings)
Audio event recognition
AudioSet-YAMNet
Audio event recognition (520 audio event classes):

Speech, Child speech, kid speaking, Conversation, Narration, monologue, Babbling, Speech synthesizer, Shout, Bellow, Whoop,
Yell, Children shouting, Screaming, Whispering, Laughter, Baby laughter, Giggle, Snicker, Belly laugh, Chuckle, chortle,
Crying, sobbing, Baby cry, infant cry, Whimper, Wail, moan, Sigh, Singing, Choir, Yodeling, Chant, Mantra, Child singing,
Synthetic singing, Rapping, Humming, Groan, Grunt, Whistling, Breathing, Wheeze, Snoring, Gasp, Pant, Snort, Cough, Throat
clearing, Sneeze, Sniff, Run, Shuffle, Walk, footsteps, Chewing, mastication, Biting, Gargling, Stomach rumble, Burping,
eructation, Hiccup, Fart, Hands, Finger snapping, Clapping, Heart sounds, heartbeat, Heart murmur, Cheering, Applause, Chatter,
Crowd, Hubbub, speech noise, speech babble, Children playing, Animal, Domestic animals, pets, Dog, Bark, Yip, Howl, Bow-wow,
Growling, Whimper (dog), Cat, Purr, Meow, Hiss, Caterwaul, Livestock, farm animals, working animals, Horse, Clip-clop, Neigh,
whinny, Cattle, bovinae, Moo, Cowbell, Pig, Oink, Goat, Bleat, Sheep, Fowl, Chicken, rooster, Cluck, Crowing,
cock-a-doodle-doo, Turkey, Gobble, Duck, Quack, Goose, Honk, Wild animals, Roaring cats (lions, tigers), Roar, Bird, Bird
vocalization, bird call, bird song, Chirp, tweet, Squawk, Pigeon, dove, Coo, Crow, Caw, Owl, Hoot, Bird flight, flapping wings,
Canidae, dogs, wolves, Rodents, rats, mice, Mouse, Patter, Insect, Cricket, Mosquito, Fly, housefly, Buzz, Bee, wasp, etc.,
Frog, Croak, Snake, Rattle, Whale vocalization, Music, Musical instrument, Plucked string instrument, Guitar, Electric guitar,
Bass guitar, Acoustic guitar, Steel guitar, slide guitar, Tapping (guitar technique), Strum, Banjo, Sitar, Mandolin, Zither,
Ukulele, Keyboard (musical), Piano, Electric piano, Organ, Electronic organ, Hammond organ, Synthesizer, Sampler, Harpsichord,
Percussion, Drum kit, Drum machine, Drum, Snare drum, Rimshot, Drum roll, Bass drum, Timpani, Tabla, Cymbal, Hi-hat, Wood
block, Tambourine, Rattle (instrument), Maraca, Gong, Tubular bells, Mallet percussion, Marimba, xylophone, Glockenspiel,
Vibraphone, Steelpan, Orchestra, Brass instrument, French horn, Trumpet, Trombone, Bowed string instrument, String section,
Violin, fiddle, Pizzicato, Cello, Double bass, Wind instrument, woodwind instrument, Flute, Saxophone, Clarinet, Harp, Bell,
Church bell, Jingle bell, Bicycle bell, Tuning fork, Chime, Wind chime, Change ringing (campanology), Harmonica, Accordion,
Bagpipes, Didgeridoo, Shofar, Theremin, Singing bowl, Scratching (performance technique), Pop music, Hip hop music, Beatboxing,
Rock music, Heavy metal, Punk rock, Grunge, Progressive rock, Rock and roll, Psychedelic rock, Rhythm and blues, Soul music,
Reggae, Country, Swing music, Bluegrass, Funk, Folk music, Middle Eastern music, Jazz, Disco, Classical music, Opera,
Electronic music, House music, Techno, Dubstep, Drum and bass, Electronica, Electronic dance music, Ambient music, Trance
music, Music of Latin America, Salsa music, Flamenco, Blues, Music for children, New-age music, Vocal music, A capella, Music
of Africa, Afrobeat, Christian music, Gospel music, Music of Asia, Carnatic music, Music of Bollywood, Ska, Traditional music,
Independent music, Song, Background music, Theme music, Jingle (music), Soundtrack music, Lullaby, Video game music, Christmas
music, Dance music, Wedding music, Happy music, Sad music, Tender music, Exciting music, Angry music, Scary music, Wind,
Rustling leaves, Wind noise (microphone), Thunderstorm, Thunder, Water, Rain, Raindrop, Rain on surface, Stream, Waterfall,
Ocean, Waves, surf, Steam, Gurgling, Fire, Crackle, Vehicle, Boat, Water vehicle, Sailboat, sailing ship, Rowboat, canoe,
kayak, Motorboat, speedboat, Ship, Motor vehicle (road), Car, Vehicle horn, car horn, honking, Toot, Car alarm, Power windows,
electric windows, Skidding, Tire squeal, Car passing by, Race car, auto racing, Truck, Air brake, Air horn, truck horn,
Reversing beeps, Ice cream truck, ice cream van, Bus, Emergency vehicle, Police car (siren), Ambulance (siren), Fire engine,
fire truck (siren), Motorcycle, Traffic noise, roadway noise, Rail transport, Train, Train whistle, Train horn, Railroad car,
train wagon, Train wheels squealing, Subway, metro, underground, Aircraft, Aircraft engine, Jet engine, Propeller, airscrew,
Helicopter, Fixed-wing aircraft, airplane, Bicycle, Skateboard, Engine, Light engine (high frequency), Dental drill, dentist's
drill, Lawn mower, Chainsaw, Medium engine (mid frequency), Heavy engine (low frequency), Engine knocking, Engine starting,
Idling, Accelerating, revving, vroom, Door, Doorbell, Ding-dong, Sliding door, Slam, Knock, Tap, Squeak, Cupboard open or
close, Drawer open or close, Dishes, pots, and pans, Cutlery, silverware, Chopping (food), Frying (food), Microwave oven,
Blender, Water tap, faucet, Sink (filling or washing), Bathtub (filling or washing), Hair dryer, Toilet flush, Toothbrush,
Electric toothbrush, Vacuum cleaner, Zipper (clothing), Keys jangling, Coin (dropping), Scissors, Electric shaver, electric
razor, Shuffling cards, Typing, Typewriter, Computer keyboard, Writing, Alarm, Telephone, Telephone bell ringing, Ringtone,
Telephone dialing, DTMF, Dial tone, Busy signal, Alarm clock, Siren, Civil defense siren, Buzzer, Smoke detector, smoke alarm,
Fire alarm, Foghorn, Whistle, Steam whistle, Mechanisms, Ratchet, pawl, Clock, Tick, Tick-tock, Gears, Pulleys, Sewing machine,
Mechanical fan, Air conditioning, Cash register, Printer, Camera, Single-lens reflex camera, Tools, Hammer, Jackhammer, Sawing,
Filing (rasp), Sanding, Power tool, Drill, Explosion, Gunshot, gunfire, Machine gun, Fusillade, Artillery fire, Cap gun,
Fireworks, Firecracker, Burst, pop, Eruption, Boom, Wood, Chop, Splinter, Crack, Glass, Chink, clink, Shatter, Liquid, Splash,
splatter, Slosh, Squish, Drip, Pour, Trickle, dribble, Gush, Fill (with liquid), Spray, Pump (liquid), Stir, Boiling, Sonar,
Arrow, Whoosh, swoosh, swish, Thump, thud, Thunk, Electronic tuner, Effects unit, Chorus effect, Basketball bounce, Bang, Slap,
smack, Whack, thwack, Smash, crash, Breaking, Bouncing, Whip, Flap, Scratch, Scrape, Rub, Roll, Crushing, Crumpling, crinkling,
Tearing, Beep, bleep, Ping, Ding, Clang, Squeal, Creak, Rustle, Whir, Clatter, Sizzle, Clicking, Clickety-clack, Rumble, Plop,
Jingle, tinkle, Hum, Zing, Boing, Crunch, Silence, Sine wave, Harmonic, Chirp tone, Sound effect, Pulse, Inside, small room,
Inside, large room or hall, Inside, public space, Outside, urban or manmade, Outside, rural or natural, Reverberation, Echo,
Noise, Environmental noise, Static, Mains hum, Distortion, Sidetone, Cacophony, White noise, Pink noise, Throbbing, Vibration,
Television, Radio, Field recording
Models:

⬇️ audioset-yamnet

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictVGGish

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="activations")
predictions = model(audio)
Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictVGGish

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = TensorflowPredictVGGish(graphFilename="audioset-yamnet-1.pb", input="melspectrogram", output="embeddings")
embeddings = model(audio)
FSD-SINet
Audio event recognition using the FSD50K dataset targeting 200 classes drawn from the AudioSet Ontology. The Shift Invariant Network (SINet) is offered in two different model sizes. vgg42 is a variation of vgg41 with twice the number of filters for each convolutional layer. Also, the shift-invariance technique may be trainable low-pass filters (tlpf), adaptative polyphase sampling (aps), or both (tlpf_aps):

Accelerating and revving and vroom, Accordion, Acoustic guitar, Aircraft, Alarm, Animal, Applause, Bark, Bass drum, Bass
guitar, Bathtub (filling or washing), Bell, Bicycle, Bicycle bell, Bird, Bird vocalization and bird call and bird song, Boat
and Water vehicle, Boiling, Boom, Bowed string instrument, Brass instrument, Breathing, Burping and eructation, Bus, Buzz,
Camera, Car, Car passing by, Cat, Chatter, Cheering, Chewing and mastication, Chicken and rooster, Child speech and kid
speaking, Chime, Chink and clink, Chirp and tweet, Chuckle and chortle, Church bell, Clapping, Clock, Coin (dropping), Computer
keyboard, Conversation, Cough, Cowbell, Crack, Crackle, Crash cymbal, Cricket, Crow, Crowd, Crumpling and crinkling, Crushing,
Crying and sobbing, Cupboard open or close, Cutlery and silverware, Cymbal, Dishes and pots and pans, Dog, Domestic animals and
pets, Domestic sounds and home sounds, Door, Doorbell, Drawer open or close, Drill, Drip, Drum, Drum kit, Electric guitar,
Engine, Engine starting, Explosion, Fart, Female singing, Female speech and woman speaking, Fill (with liquid), Finger
snapping, Fire, Fireworks, Fixed-wing aircraft and airplane, Fowl, Frog, Frying (food), Gasp, Giggle, Glass, Glockenspiel,
Gong, Growling, Guitar, Gull and seagull, Gunshot and gunfire, Gurgling, Hammer, Hands, Harmonica, Harp, Hi-hat, Hiss, Human
group actions, Human voice, Idling, Insect, Keyboard (musical), Keys jangling, Knock, Laughter, Liquid, Livestock and farm
animals and working animals, Male singing, Male speech and man speaking, Mallet percussion, Marimba and xylophone, Mechanical
fan, Mechanisms, Meow, Microwave oven, Motor vehicle (road), Motorcycle, Music, Musical instrument, Ocean, Organ, Packing tape
and duct tape, Percussion, Piano, Plucked string instrument, Pour, Power tool, Printer, Purr, Race car and auto racing, Rail
transport, Rain, Raindrop, Ratchet and pawl, Rattle, Rattle (instrument), Respiratory sounds, Ringtone, Run, Sawing, Scissors,
Scratching (performance technique), Screaming, Screech, Shatter, Shout, Sigh, Singing, Sink (filling or washing), Siren,
Skateboard, Slam, Sliding door, Snare drum, Sneeze, Speech, Speech synthesizer, Splash and splatter, Squeak, Stream, Strum,
Subway and metro and underground, Tabla, Tambourine, Tap, Tearing, Telephone, Thump and thud, Thunder, Thunderstorm, Tick,
Tick-tock, Toilet flush, Tools, Traffic noise and roadway noise, Train, Trickle and dribble, Truck, Trumpet, Typewriter,
Typing, Vehicle, Vehicle horn and car horn and honking, Walk and footsteps, Water, Water tap and faucet, Waves and surf,
Whispering, Whoosh and swoosh and swish, Wild animals, Wind, Wind chime, Wind instrument and woodwind instrument, Wood,
Writing, Yell, Zipper (clothing)
Models:

⬇️ fsd-sinet-vgg41-tlpf

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg41-tlpf-1.pb")
predictions = model(audio)
Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg41-tlpf-1.pb", output="model/global_max_pooling1d/Max")
embeddings = model(audio)
⬇️ fsd-sinet-vgg42-aps

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg42-aps-1.pb")
predictions = model(audio)
Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg42-aps-1.pb", output="model/global_max_pooling1d/Max")
embeddings = model(audio)
⬇️ fsd-sinet-vgg42-tlpf_aps

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg42-tlpf_aps-1.pb")
predictions = model(audio)
Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg42-tlpf_aps-1.pb", output="model/global_max_pooling1d/Max")
embeddings = model(audio)
⬇️ fsd-sinet-vgg42-tlpf

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg42-tlpf-1.pb")
predictions = model(audio)
Python code for embedding extraction:

from essentia.standard import MonoLoader, TensorflowPredictFSDSINet

audio = MonoLoader(filename="audio.wav", sampleRate=22050, resampleQuality=4)()
model = TensorflowPredictFSDSINet(graphFilename="fsd-sinet-vgg42-tlpf-1.pb", output="model/global_max_pooling1d/Max")
embeddings = model(audio)
Pitch detection
CREPE
Monophonic pitch detection (360 20-cent pitch bins, C1-B7) trained on the RWC-synth and the MDB-stem-synth datasets. CREPE is offered with different model sizes ranging from tiny to full. A larger model is expected to perform better at the expense of additional computational costs.

Models:

⬇️ crepe-full

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, PitchCREPE

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = PitchCREPE(graphFilename="crepe-full-1.pb")
time, frequency, confidence, activations = model(audio)
⬇️ crepe-large

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, PitchCREPE

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = PitchCREPE(graphFilename="crepe-large-1.pb")
time, frequency, confidence, activations = model(audio)
⬇️ crepe-medium

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, PitchCREPE

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = PitchCREPE(graphFilename="crepe-medium-1.pb")
time, frequency, confidence, activations = model(audio)
⬇️ crepe-small

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, PitchCREPE

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = PitchCREPE(graphFilename="crepe-small-1.pb")
time, frequency, confidence, activations = model(audio)
⬇️ crepe-tiny

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, PitchCREPE

audio = MonoLoader(filename="audio.wav", sampleRate=16000, resampleQuality=4)()
model = PitchCREPE(graphFilename="crepe-tiny-1.pb")
time, frequency, confidence, activations = model(audio)
Source separation
Spleeter
Source separation into 2, 4, or 5 stems. Spleeter can separate music in different numbers of stems: 2 (vocals and accompaniment), 4 (vocals, drums, bass, and other separation), or 5 (vocals, drums, bass, piano, and other separation).

Models:

⬇️ speeter-2s

[weights, metadata]

Python code for source separation:

from essentia.standard import AudioLoader, TensorflowPredict
from essentia import Pool
import numpy as np

# Input should be audio @41kHz.
audio, sr, _, _, _, _ = AudioLoader(filename="audio.wav")()

pool = Pool()
# The input needs to have 4 dimensions so that it is interpreted as an Essentia tensor.
pool.set("waveform", audio[..., np.newaxis, np.newaxis])

model = TensorflowPredict(
    graphFilename="spleeter-2s-3.pb",
    inputs=["waveform"],
    outputs=["waveform_vocals", "waveform_accompaniment"]
)

out_pool = model(pool)
vocals = out_pool["waveform_vocals"].squeeze()
accompaniment = out_pool["waveform_accompaniment"].squeeze()
⬇️ speeter-4s

[weights, metadata]

Python code for source separation:

from essentia.standard import AudioLoader, TensorflowPredict
from essentia import Pool
import numpy as np

# Input should be audio @41kHz.
audio, sr, _, _, _, _ = AudioLoader(filename="audio.wav")()

pool = Pool()
# The input needs to have 4 dimensions so that it is interpreted as an Essentia tensor.
pool.set("waveform", audio[..., np.newaxis, np.newaxis])

model = TensorflowPredict(
    graphFilename="spleeter-4s-3.pb",
    inputs=["waveform"],
    outputs=["waveform_vocals", "waveform_drums", "waveform_bass", "waveform_other"]
)

out_pool = model(pool)
vocals = out_pool["waveform_vocals"].squeeze()
drums = out_pool["waveform_drums"].squeeze()
bass = out_pool["waveform_bass"].squeeze()
other = out_pool["waveform_other"].squeeze()
⬇️ speeter-5s

[weights, metadata]

Python code for source separation:

from essentia.standard import AudioLoader, TensorflowPredict
from essentia import Pool
import numpy as np

# Input should be audio @41kHz.
audio, sr, _, _, _, _ = AudioLoader(filename="audio.wav")()

pool = Pool()
# The input needs to have 4 dimensions so that it is interpreted as an Essentia tensor.
pool.set("waveform", audio[..., np.newaxis, np.newaxis])

model = TensorflowPredict(
    graphFilename="spleeter-5s-3.pb",
    inputs=["waveform"],
    outputs=["waveform_vocals", "waveform_drums", "waveform_bass", "waveform_piano", "waveform_other"]
)

out_pool = model(pool)
vocals = out_pool["waveform_vocals"].squeeze()
drums = out_pool["waveform_drums"].squeeze()
bass = out_pool["waveform_bass"].squeeze()
bass = out_pool["waveform_piano"].squeeze()
other = out_pool["waveform_other"].squeeze()
Tempo estimation
TempoCNN
Tempo classification (256 BPM classes, 30-286 BPM) trained on the Extended Ballroom, LMDTempo, and MTGTempo datasets. TempoCNN may feature square filters (deepsquare) or longitudinal ones (deeptemp) and a model size factor of 4 (k4) or 16 (k16). A larger model is expected to perform better at the expense of additional computational costs.

Models:

⬇️ deepsquare-k16

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TempoCNN

audio = MonoLoader(filename="audio.wav", sampleRate=11025, resampleQuality=4)()
model = TempoCNN(graphFilename="deepsquare-k16-3.pb")
global_tempo, local_tempo, local_tempo_probabilities = model(audio)
⬇️ deeptemp-k4

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TempoCNN

audio = MonoLoader(filename="audio.wav", sampleRate=11025, resampleQuality=4)()
model = TempoCNN(graphFilename="deeptemp-k4-3.pb")
global_tempo, local_tempo, local_tempo_probabilities = model(audio)
⬇️ deeptemp-k16

[weights, metadata]

Python code for predictions:

from essentia.standard import MonoLoader, TempoCNN

audio = MonoLoader(filename="audio.wav", sampleRate=11025, resampleQuality=4)()
model = TempoCNN(graphFilename="deeptemp-k16-3.pb")
global_tempo, local_tempo, local_tempo_probabilities = model(audio)