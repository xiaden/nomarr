# Essentia Pre-trained Models

## License

All models in this directory are licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0)**.

**Copyright © Music Technology Group, Universitat Pompeu Fabra**

### License Terms

You are free to:

- **Share** — copy and redistribute the models in any medium or format
- **Adapt** — remix, transform, and build upon the models

Under the following terms:

- **Attribution** — You must give appropriate credit to Music Technology Group, Universitat Pompeu Fabra, provide a link to the license, and indicate if changes were made.
- **NonCommercial** — You may not use the models for commercial purposes.
- **ShareAlike** — If you remix, transform, or build upon the models, you must distribute your contributions under the same CC BY-NC-SA 4.0 license.

### Full License

https://creativecommons.org/licenses/by-nc-sa/4.0/

### Commercial Licensing

For commercial licensing of these models, please contact:

- Music Technology Group
- Universitat Pompeu Fabra
- Barcelona, Spain
- https://www.upf.edu/web/mtg/contact

## Source

These models are from the Essentia project:

- Homepage: https://essentia.upf.edu/
- Models: https://essentia.upf.edu/models.html
- GitHub: https://github.com/MTG/essentia

## Citation

If you use these models in your research, please cite:

```bibtex
@inproceedings{alonso2020tensorflow,
  title={Tensorflow Audio Models in {Essentia}},
  author={Alonso-Jim{\'e}nez, Pablo and Bogdanov, Dmitry and Pons, Jordi and Serra, Xavier},
  booktitle={International Conference on Acoustics, Speech and Signal Processing ({ICASSP})},
  year={2020}
}
```

## Model Descriptions

See `docs/modelsinfo.md` for detailed information about each model, including:

- Feature extractors (VGGish, EffNet, YAMNet)
- Classification models (genre, mood, instruments, voice)
- Audio embeddings and similarity models

## Directory Structure

```
models/
├── effnet/
│   ├── embeddings/     # Embedding models (.pb + .json)
│   └── heads/          # Classification heads (.pb + .json)
├── yamnet/
│   ├── embeddings/
│   └── heads/
└── README.md           # This file
```

Each model consists of:

- `.pb` file - TensorFlow graph weights
- `.json` file - Model metadata and configuration
