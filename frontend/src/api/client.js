import axios from 'axios';
import { auth } from '../firebase.js';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 60000,
});

client.interceptors.request.use(async (config) => {
  const user = auth.currentUser;
  if (user) {
    try {
      const token = await user.getIdToken();
      config.headers['Authorization'] = `Bearer ${token}`;
    } catch {
      // If token fetch fails, proceed without auth header — server will 401
    }
  }
  return config;
});

export default client;
