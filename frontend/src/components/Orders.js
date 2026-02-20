import React, { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Card, Col, Form, Image, Input, message, Modal, Row, Select, Space, Statistic, Table, Tag } from 'antd';
import { ShoppingCartOutlined, SyncOutlined, UserOutlined } from '@ant-design/icons';
import axios from 'axios';
import dayjs from 'dayjs';

const { Option } = Select;

const statusOptions = [
  { value: 'draft', label: 'Черновик' },
  { value: 'new', label: 'Новая заявка' },
  { value: 'in_work', label: 'В работе' },
  { value: 'done', label: 'Готово' },
  { value: 'canceled', label: 'Отменено' },
];

const statusColor = {
  draft: 'default',
  new: 'blue',
  in_work: 'orange',
  done: 'green',
  canceled: 'red',
};

const Orders = () => {
  const [orders, setOrders] = useState([]);
  const [stats, setStats] = useState({ total_orders: 0, new_orders: 0, active_orders: 0 });
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState();
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [files, setFiles] = useState([]);
  const [chatMessages, setChatMessages] = useState([]);
  const [sending, setSending] = useState(false);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get('/api/orders/', { params: { status_filter: statusFilter } });
      setOrders(data);
    } catch {
      message.error('Не удалось загрузить заявки');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/orders/stats');
      setStats(data);
    } catch {
      setStats({ total_orders: 0, new_orders: 0, active_orders: 0 });
      message.warning('Статистика временно недоступна');
    }
  }, []);

  useEffect(() => {
    fetchOrders();
    fetchStats();
  }, [fetchOrders, fetchStats]);

  const openOrder = async (order) => {
    setSelectedOrder(order);
    setModalVisible(true);
    try {
      const [filesResp, msgResp] = await Promise.all([
        axios.get(`/api/orders/${order.id}/files`),
        axios.get(`/api/orders/${order.id}/messages`),
      ]);
      setFiles(filesResp.data.files || []);
      setChatMessages(msgResp.data.messages || []);
    } catch {
      setFiles([]);
      setChatMessages([]);
      message.warning('Не удалось загрузить файлы или чат по заявке');
    }
  };

  const sendManagerMessage = async (values) => {
    if (!selectedOrder) return;
    setSending(true);
    try {
      await axios.post(`/api/orders/${selectedOrder.id}/messages`, { text: values.text });
      message.success('Сообщение отправлено в Telegram');
      const { data } = await axios.get(`/api/orders/${selectedOrder.id}/messages`);
      setChatMessages(data.messages || []);
    } catch (err) {
      message.error(err?.response?.data?.detail || 'Не удалось отправить сообщение в Telegram');
    } finally {
      setSending(false);
    }
  };

  const updateStatus = async (id, status) => {
    try {
      await axios.put(`/api/orders/${id}`, { status });
      fetchOrders();
    } catch (err) {
      message.error(err?.response?.data?.detail || 'Не удалось обновить статус');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: 'Клиент', render: (_, r) => `${r.full_name || 'Без имени'} (@${r.username || '-'})` },
    { title: 'Тип заявки', dataIndex: 'branch' },
    { title: 'Кратко', dataIndex: 'summary' },
    {
      title: 'Статус',
      render: (_, r) => (
        <Select value={r.status} style={{ width: 150 }} onChange={(v) => updateStatus(r.id, v)}>
          {statusOptions.map((s) => <Option key={s.value} value={s.value}>{s.label}</Option>)}
        </Select>
      )
    },
    { title: 'Дата', dataIndex: 'created_at', render: (v) => dayjs(v).format('DD.MM.YYYY HH:mm') },
    { title: 'Открыть', render: (_, r) => <Button onClick={() => openOrder(r)}>Карточка</Button> },
  ];

  return (
    <div>
      <h1>Заявки Chel3D</h1>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title='Всего заявок' value={stats.total_orders} prefix={<ShoppingCartOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title='Новых' value={stats.new_orders} prefix={<UserOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title='Активных' value={stats.active_orders} prefix={<SyncOutlined />} />
          </Card>
        </Col>
      </Row>
      <Space style={{ marginBottom: 12 }}>
        <span>Фильтр:</span>
        <Select allowClear placeholder='Все статусы' style={{ width: 220 }} onChange={setStatusFilter}>
          {statusOptions.map((s) => <Option key={s.value} value={s.value}>{s.label}</Option>)}
        </Select>
      </Space>
      <Table rowKey='id' loading={loading} columns={columns} dataSource={orders} />

      <Space style={{ marginBottom: 12 }}>
        <Select
          allowClear
          placeholder="Фильтр статуса"
          style={{ width: 220 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
        >
          {statusOptions.map((s) => <Option key={s.value} value={s.value}>{s.label}</Option>)}
        </Select>
        <Button icon={<SyncOutlined />} onClick={fetchOrders}>Обновить</Button>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={orders}
        columns={columns}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        open={modalVisible}
        title={selectedOrder ? `Заявка #${selectedOrder.id}` : 'Заявка'}
        onCancel={() => setModalVisible(false)}
        footer={null}
        width={900}
      >
        {selectedOrder && (
          <Row gutter={16}>
            <Col span={12}>
              <Card title="Информация" style={{ marginBottom: 12 }}>
                <p><b>Клиент:</b> {selectedOrder.full_name || 'Без имени'} (@{selectedOrder.username || '-'})</p>
                <p><b>Тип:</b> {selectedOrder.branch}</p>
                <p>
                  <b>Статус:</b>{' '}
                  <Tag color={statusColor[selectedOrder.status] || 'default'}>
                    {statusOptions.find((s) => s.value === selectedOrder.status)?.label || selectedOrder.status}
                  </Tag>
                </p>
                <p><b>Кратко:</b> {selectedOrder.summary || '-'}</p>
              </Card>

              <Card title="Файлы">
                {files.length === 0 && <p>Нет файлов</p>}
                {files.map((f) => (
                  <div key={f.id} style={{ marginBottom: 10 }}>
                    <div><b>{f.original_name || f.telegram_file_id}</b></div>
                    {f.file_url ? (
                      <Image width={180} src={f.file_url} />
                    ) : (
                      <Badge status="processing" text="URL не найден (возможно, файл не картинка)" />
                    )}
                  </div>
                ))}
              </Card>
            </Col>

            <Col span={12}>
              <Card title="Чат с клиентом" style={{ marginBottom: 12 }}>
                {chatMessages.length === 0 && <p>Сообщений пока нет</p>}
                {chatMessages.map((m) => (
                  <div key={m.id} style={{ padding: 8, borderBottom: '1px solid #f0f0f0' }}>
                    <Tag>{m.direction === 'in' ? 'Входящее' : 'Исходящее'}</Tag>
                    <div style={{ whiteSpace: 'pre-wrap' }}>{m.message_text}</div>
                    <div style={{ fontSize: 12, opacity: 0.7 }}>{dayjs(m.created_at).format('DD.MM.YYYY HH:mm')}</div>
                  </div>
                ))}
              </Card>

              <Card title="Отправить сообщение клиенту">
                <Form onFinish={sendManagerMessage} layout="vertical">
                  <Form.Item
                    name="text"
                    label="Текст"
                    rules={[{ required: true, message: 'Введите текст' }]}
                  >
                    <Input.TextArea rows={4} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={sending}>
                    Отправить в Telegram
                  </Button>
                </Form>
              </Card>
            </Col>
          </Row>
        )}
      </Modal>
    </div>
  );
};

export default Orders;
