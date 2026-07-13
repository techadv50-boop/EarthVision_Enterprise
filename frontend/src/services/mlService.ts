import { api } from './api';

export const mlService = {
  async getDemoDataset(nSamples = 400) {
    const { data } = await api.get('/ml/demo-dataset', {
      params: { n_samples: nSamples },
    });
    return data as { features: number[][]; labels: number[]; n_classes: number };
  },

  async train(payload: {
    algorithm: 'random_forest' | 'svm' | 'deep_learning';
    task: string;
    features: number[][];
    labels: number[];
  }) {
    const { data } = await api.post('/ml/train', payload);
    return data;
  },

  async predict(modelId: string, features: number[][]) {
    const { data } = await api.post('/ml/predict', { model_id: modelId, features });
    return data;
  },

  async changeDetection(before: number[], after: number[], threshold = 0.15) {
    const { data } = await api.post('/ml/change-detection', {
      before_values: before,
      after_values: after,
      threshold,
      method: 'normalized',
    });
    return data;
  },
};
