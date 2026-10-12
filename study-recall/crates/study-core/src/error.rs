use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("{0}")]
    NotFound(String),
    #[error("{0}")]
    Invalid(String),
    #[error("{0}")]
    Conflict(String),
    #[error("database error: {0}")]
    Database(String),
    #[error("{0}")]
    Backup(String),
}

impl From<rusqlite::Error> for AppError {
    fn from(value: rusqlite::Error) -> Self {
        AppError::Database(value.to_string())
    }
}

pub type AppResult<T> = Result<T, AppError>;
