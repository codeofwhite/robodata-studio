export type Session = {
  id: string;
  dataset_id: number;
  dataset_name?: string;
  adapter_id: string;
  engine_id: 'genesis' | 'isaac_sim' | 'roboverse';
  scene_id: string;
  control_mode: 'keyboard' | 'gello' | 'scripted' | 'imported';
  status: string;
  target_episodes: number;
  collector_url: string | null;
  worker_pid: number | null;
  episode_count?: number;
  accepted_count?: number;
  pending_count?: number;
  created_at: string;
  updated_at: string;
  config: Record<string, unknown>;
};

export type WorkerRuntime = {
  status: 'not_managed' | 'starting' | 'running' | 'stopping' | 'stopped' | 'failed' | 'orphaned';
  run_id: string | null;
  pid: number | null;
  supervisor_pid: number | null;
  child_pid: number | null;
  return_code?: number | null;
  ready_at?: string | null;
  heartbeat_at?: string | null;
  error?: string | null;
  log_path?: string;
  engine_id?: string;
  resources: string[];
};

export type Dataset = {
  id: number;
  name: string;
  root_path: string;
  session_count: number;
  episode_count: number;
  accepted_count: number;
  genesis_episode_count: number;
  isaac_episode_count: number;
  roboverse_episode_count: number;
  genesis_accepted_count: number;
  isaac_accepted_count: number;
  roboverse_accepted_count: number;
  genesis_pending_count: number;
  isaac_pending_count: number;
  roboverse_pending_count: number;
  created_at: string;
};

export type Episode = {
  id: number;
  session_id: string;
  dataset_id: number;
  engine_id: 'genesis' | 'isaac_sim' | 'roboverse';
  engine_version: string | null;
  worker_id: string | null;
  episode_index: number | null;
  episode_uuid: string;
  path: string;
  task: string;
  scene_id: string;
  control_mode: string;
  control_source: string | null;
  seed: number | null;
  source_trajectory: string | null;
  duplicate_group_size: number;
  is_duplicate: boolean;
  operator_success: number | null;
  auto_success: number | null;
  qa_status: 'pending' | 'accepted' | 'rejected';
  failure_reason: string | null;
  num_frames: number;
  fps: number | null;
  duration_s: number | null;
  created_at: string | null;
  manifest?: {
    camera_names?: string[];
    fps?: number;
    episode_metrics?: Record<string, unknown>;
    software?: { engine_id?: string; engine_version?: string; worker_id?: string };
    scene?: { scene_id?: string; seed?: number };
    control_source?: string;
  };
  trajectory?: Record<string, number[] | number[][]>;
};

export type ExportEpisodeRef = {
  episode_id: number;
  session_id: string;
  episode_index: number | null;
  engine_id: 'genesis' | 'isaac_sim' | 'roboverse' | null;
  engine_version: string | null;
  worker_id: string | null;
  scene_id: string | null;
  position: number;
};

export type ExportPreflight = {
  compatible: true;
  dataset_id: number;
  dataset_name: string;
  episode_ids: number[];
  episode_count: number;
  engine_counts: Record<string, number>;
  engine_ids: string[];
  scene_ids: string[];
  robot_id: string;
  fps: number;
  action_profile: string;
  training_profile: string;
  camera_names: string[];
  optional_observations: string[];
  provenance_complete: boolean;
  warnings: string[];
};

export type ExportJob = {
  id: string;
  dataset_id: number;
  format: 'lerobot' | 'openpi_lerobot_v21' | 'rlds' | 'robomimic';
  status: string;
  output_path: string;
  error: string | null;
  output_name: string | null;
  repo_id: string | null;
  images: number | null;
  profile: 'physical_joint8' | 'openpi_franka_joint8' | 'fastwam_franka_joint8' | null;
  episode_count: number;
  episode_ids: number[];
  episode_refs: ExportEpisodeRef[];
  created_at: string;
};

export type ConsumerSmoke = {
  id: string;
  export_id: string;
  consumer: 'openpi' | 'fastwam';
  status: 'queued' | 'running' | 'passed' | 'failed';
  report_path: string;
  log_path: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  report: {
    weight_forward?: {
      weights_loaded: boolean;
      model_forward_passed: boolean;
      contract_compatible?: boolean;
      deployment_compatible: boolean;
      closed_loop_validated?: boolean;
      training_evidence?: string;
      actions?: { shape: number[] | null; dtype: string | null };
      policy_infer_ms?: number;
      compatibility_reason?: string;
    };
  } | null;
  report_read_error?: string;
};
