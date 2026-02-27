from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Room, RoomMember, Task, Expense, ExpenseShare


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class RoomMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = RoomMember
        fields = ['id', 'user', 'user_id', 'room', 'is_admin', 'joined_at']
        read_only_fields = ['joined_at']


class RoomSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    members = RoomMemberSerializer(many=True, read_only=True, source='members')
    member_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'code', 'description', 'owner', 'members', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_member_count(self, obj):
        return obj.members.count()


class TaskSerializer(serializers.ModelSerializer):
    assigned_to = UserSerializer(read_only=True)
    assigned_to_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = Task
        fields = ['id', 'room', 'title', 'description', 'assigned_to', 'assigned_to_id', 'status', 
                  'priority', 'due_date', 'created_by', 'created_at', 'updated_at', 'completed_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class ExpenseShareSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = ExpenseShare
        fields = ['id', 'expense', 'user', 'amount', 'is_settled']


class ExpenseSerializer(serializers.ModelSerializer):
    paid_by = UserSerializer(read_only=True)
    paid_by_id = serializers.IntegerField(write_only=True)
    shares = ExpenseShareSerializer(many=True, read_only=True)
    
    class Meta:
        model = Expense
        fields = ['id', 'room', 'description', 'amount', 'paid_by', 'paid_by_id', 'date', 
                  'category', 'shares', 'created_at', 'updated_at']
        read_only_fields = ['id', 'shares', 'created_at', 'updated_at']
