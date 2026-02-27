// Конфигурация API
const API_BASE = '/api';
const CSRF_TOKEN = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

// Утилиты для работы с API
async function apiCall(method, endpoint, data = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN,
        }
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            throw new Error(`HTTP Error: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Функции для работы с комнатами
async function getRooms() {
    try {
        return await apiCall('GET', '/rooms/');
    } catch (error) {
        console.error('Ошибка при загрузке комнат:', error);
        return [];
    }
}

async function createRoom(name, description) {
    try {
        return await apiCall('POST', '/rooms/', { name, description });
    } catch (error) {
        console.error('Ошибка при создании комнаты:', error);
        throw error;
    }
}

async function joinRoom(code) {
    try {
        return await apiCall('POST', '/rooms/join_room/', { code });
    } catch (error) {
        console.error('Ошибка при присоединении к комнате:', error);
        throw error;
    }
}

async function getRoomStats(roomId) {
    try {
        return await apiCall('GET', `/rooms/${roomId}/statistics/`);
    } catch (error) {
        console.error('Ошибка при загрузке статистики:', error);
        return null;
    }
}

// Функции для работы с задачами
async function getTasks(roomId = null) {
    try {
        let endpoint = '/tasks/';
        if (roomId) {
            endpoint += `?room=${roomId}`;
        }
        return await apiCall('GET', endpoint);
    } catch (error) {
        console.error('Ошибка при загрузке задач:', error);
        return [];
    }
}

async function createTask(roomId, title, description, assignedToId = null, priority = 'medium') {
    try {
        return await apiCall('POST', '/tasks/', {
            room: roomId,
            title,
            description,
            assigned_to_id: assignedToId,
            priority,
            status: 'pending'
        });
    } catch (error) {
        console.error('Ошибка при создании задачи:', error);
        throw error;
    }
}

async function updateTask(taskId, data) {
    try {
        return await apiCall('PATCH', `/tasks/${taskId}/`, data);
    } catch (error) {
        console.error('Ошибка при обновлении задачи:', error);
        throw error;
    }
}

async function completeTask(taskId) {
    try {
        return await apiCall('POST', `/tasks/${taskId}/complete/`);
    } catch (error) {
        console.error('Ошибка при завершении задачи:', error);
        throw error;
    }
}

// Функции для работы с расходами
async function getExpenses(roomId = null) {
    try {
        let endpoint = '/expenses/';
        if (roomId) {
            endpoint += `?room=${roomId}`;
        }
        return await apiCall('GET', endpoint);
    } catch (error) {
        console.error('Ошибка при загрузке расходов:', error);
        return [];
    }
}

async function createExpense(roomId, description, amount, paidById, category, shares) {
    try {
        return await apiCall('POST', '/expenses/', {
            room: roomId,
            description,
            amount,
            paid_by_id: paidById,
            category,
            shares
        });
    } catch (error) {
        console.error('Ошибка при создании расхода:', error);
        throw error;
    }
}

async function updateExpense(expenseId, data) {
    try {
        return await apiCall('PATCH', `/expenses/${expenseId}/`, data);
    } catch (error) {
        console.error('Ошибка при обновлении расхода:', error);
        throw error;
    }
}

// Функции для работы с долями расходов
async function settleExpenseShare(shareId) {
    try {
        return await apiCall('POST', `/expense-shares/${shareId}/settle/`);
    } catch (error) {
        console.error('Ошибка при отметке доли:', error);
        throw error;
    }
}

// Функции для работы с участниками
async function getRoomMembers(roomId) {
    try {
        const data = await apiCall('GET', `/rooms/${roomId}/`);
        return data.members || [];
    } catch (error) {
        console.error('Ошибка при загрузке участников:', error);
        return [];
    }
}

// Функция для форматирования даты
function formatDate(dateString) {
    const date = new Date(dateString);
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    if (date.toDateString() === today.toDateString()) {
        return `сегодня, ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
    } else if (date.toDateString() === tomorrow.toDateString()) {
        return `завтра, ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
    } else {
        const days = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];
        return `${days[date.getDay()]}, ${date.getDate()} ${getMonthName(date.getMonth())}`;
    }
}

function getMonthName(monthIndex) {
    const months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
    return months[monthIndex];
}

// Функции для отображения на странице
function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 16px 20px;
        background: ${type === 'success' ? '#2ecc71' : '#e74c3c'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;

    document.body.appendChild(notification);
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Обработчик для вступления в комнату
async function joinRoom(code) {
    if (!code || code.trim() === '') {
        showNotification('Пожалуйста, введите код комнаты', 'error');
        return;
    }

    try {
        const result = await apiCall('POST', '/rooms/join_room/', { code: code.trim() });
        showNotification(`Вы присоединились к комнате: ${result.name}`, 'success');
        // Перенаправить на панель управления
        setTimeout(() => {
            window.location.href = '/dashboard/';
        }, 1500);
    } catch (error) {
        showNotification('Неправильный код комнаты или ошибка сервера', 'error');
    }
}

// Обработчик для регистрации
async function handleRegister(event) {
    event.preventDefault();
    const fullName = document.getElementById('full-name')?.value;
    const email = document.getElementById('email')?.value;
    const password = document.getElementById('password')?.value;
    const passwordConfirm = document.getElementById('password-confirm')?.value;

    if (password !== passwordConfirm) {
        showNotification('Пароли не совпадают', 'error');
        return;
    }

    // TODO: Интегрировать с API регистрации
    showNotification('Функция регистрации еще не реализована', 'error');
}

// Функция для копирования кода комнаты
async function copyRoomCode() {
    try {
        // TODO: Получить реальный код из API
        const code = 'ABC123';
        await navigator.clipboard.writeText(code);
        showNotification(`Код скопирован: ${code}`, 'success');
    } catch (error) {
        showNotification('Ошибка при копировании', 'error');
    }
}

// Подсказка для аналитики
function initAnalytics() {
    console.log('COHUB v1.0 - Система управления совместной жизнью');
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function () {
    initAnalytics();
});
