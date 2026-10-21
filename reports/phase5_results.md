# Phase 5 — ML Classification Report

**Synthetic-label classification only.** All positive labels come from simulated transit injection (depth 75/150/225/300 ppm). Negative labels are depth=0 windows from the same observed light curves. **Not a discovery claim.**

## Design summary
- Features (7): depth_rel_ppm, contrast_ppm, mad_scatter, gap_fraction, matched_filter_corr, segment_std_ppm (segment-level variability from Phase 4), mean_flux.
- Baseline: LogisticRegression (C=1.0, max_iter=1000).
- Complex model: RandomForest (200 trees, max_depth=6) — added only if validation F1 improves by >0.05 over baseline.
- Split: segment-level (parent continuous segment split at >1d gap). No segment appears in both train and test.
- Threshold: selected on validation set via Youden index (max sensitivity + specificity - 1).

## Metrics (test set)
- **threshold**: 0.4405
- **precision**: 0.7500
- **recall**: 0.7500
- **f1**: 0.7500
- **confusion_matrix**: [[2, 1], [1, 3]]
- **roc_auc**: 0.6667
- **pr_auc**: 0.7708
- **n_train**: 13
- **n_val**: 6
- **n_test**: 7
- **positive_train**: 6
- **negative_train**: 7
- **positive_test**: 4
- **negative_test**: 3
- **feature_list**: ['depth_rel_ppm', 'contrast_ppm', 'mad_scatter', 'gap_fraction', 'matched_filter_corr', 'segment_std_ppm', 'mean_flux']
- **segment_metadata_feature_included**: segment_std_ppm (parent segment variability from Phase 4)
- **label_source_note**: Synthetic injection only (positive=depth>0 [75,150,225,300 ppm], negative=depth=0). Not real-planet labels.
- **split_strategy**: Segment-level split by parent continuous segment (gap >1d split); no overlap between train/val/test.
- **synthetic_only_warning**: Performance measured on simulated windows only. Generalization to real observations remains unverified.
- **no_discovery_claim**: True
- **dummy_f1**: 0.5714
- **baseline_f1**: 0.7500
- **improvement_vs_dummy_f1**: 0.1786
- **rf_f1_validation**: 0.8000
- **rf_selected**: False
- **rf_f1_test**: None

*Synthetic-only warning:* Performance reflects recovery of synthetic signals through the pipeline with observed noise patterns. Generalization to real exoplanet signals is unverified. Real-planet detection requires independent confirmation.
